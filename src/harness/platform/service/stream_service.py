"""流式对话服务 — 把 Agent 的流式事件转成 SSE 领域事件并增量落库。

职责：
    - 校验会话归属，落用户消息与 assistant 占位消息（status=streaming）
    - 消费 ``ReActAgent.run_stream`` 的 LoopStreamEvent，转成 StreamEvent
    - 节流把文本 / 工具块增量写回 ``session_messages``
    - 正常结束置 ``completed``，用户取消置 ``cancelled``，
      异常或客户端断线置 ``failed``（保留已生成内容）
    - 维护 ``agent_runs`` 状态与 token 用量

取消采用协作式：``POST /agents/runs/{run_id}/cancel`` 只登记标记，
本服务在下一个 Loop 事件前检查并停止生成。

事件协议（SSE 的 event 名）：
    - ``message_start``  {run_id, message_id, session_id, seq}
    - ``part_delta``     {delta}
    - ``tool_call``      {status: start|end, calls?|results?}
    - ``message_end``    {status: completed|cancelled|failed, message, metrics, error}
    - ``error``          {message}
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from harness.core.loop.streaming import (
    EVENT_ERROR,
    EVENT_TEXT_DELTA,
    EVENT_TOOL_END,
    EVENT_TOOL_START,
)
from harness.platform.api.dto.message_dto import MessageCreateRequest
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.entity.agent_run import AgentRun
from harness.platform.repository.agent_run_repository import AgentRunRepository
from harness.platform.service.message_service import MessageService
from harness.platform.service.stream_cancel import get_stream_cancel_registry
from harness.platform.service.stream_events import (
    StreamEvent,
    append_text_part,
    tool_part,
)
from harness.platform.service.stream_finalize import (
    cleanup_interrupted,
    end_event,
    finalize_stream,
)

log = logging.getLogger(__name__)

# 增量落库节流间隔（秒）：太小压库，太大断线丢字
_FLUSH_INTERVAL = 0.2


class ChatStreamService:
    """流式对话用例：Agent 生成 → SSE 事件 → 增量消息落库。"""

    def __init__(self, user: UserInfo, db) -> None:
        self.user = user
        self.db = db
        self.messages = MessageService(user, db)
        self.runs = AgentRunRepository(db)

    async def stream(self, session_id: str, goal: str) -> AsyncIterator[StreamEvent]:
        """执行一次流式对话，按事件序列产出 StreamEvent。"""
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        run_record = await self._create_run(run_id, goal, session_id)

        await self.messages.append_message(
            session_id, MessageCreateRequest(role="user", text=goal)
        )
        message = await self.messages.start_streaming_message(session_id)

        yield StreamEvent(
            "message_start",
            {
                "run_id": run_id,
                "message_id": message.id,
                "session_id": session_id,
                "seq": message.seq,
            },
        )

        text = ""
        parts: list[dict] = []
        status = "completed"
        error: str | None = None
        metrics: dict[str, int] = {}
        last_flush = time.monotonic()
        agent: Any = None
        cancel_registry = get_stream_cancel_registry()
        cancel_registry.register(run_id)

        try:
            agent = self._build_agent(run_id)
            async for event in agent.run_stream(goal):
                # 协作式取消：每个事件前检查，命中后保留已生成内容并落终态
                if cancel_registry.is_cancelled(run_id):
                    status = "cancelled"
                    error = "用户取消"
                    break
                etype = event.event_type
                if etype == EVENT_TEXT_DELTA:
                    delta = str(event.payload.get("delta") or "")
                    if not delta:
                        continue
                    text += delta
                    append_text_part(parts, delta)
                    yield StreamEvent("part_delta", {"delta": delta})
                    if time.monotonic() - last_flush >= _FLUSH_INTERVAL:
                        await self.messages.update_streaming_message(
                            message, text=text, parts=parts
                        )
                        last_flush = time.monotonic()
                elif etype == EVENT_TOOL_START:
                    yield StreamEvent(
                        "tool_call",
                        {"status": "start", "calls": event.payload.get("calls") or []},
                    )
                elif etype == EVENT_TOOL_END:
                    results = event.payload.get("results") or []
                    for item in results:
                        parts.append(tool_part(item))
                    await self.messages.update_streaming_message(
                        message, text=text, parts=parts
                    )
                    last_flush = time.monotonic()
                    yield StreamEvent(
                        "tool_call", {"status": "end", "results": results}
                    )
                elif etype == EVENT_ERROR:
                    status = "failed"
                    error = str(event.payload.get("error") or "模型调用失败")
                    yield StreamEvent("error", {"message": error})
            if status == "completed" and agent.state is not None:
                metrics = dict(agent.state.metrics)
        except GeneratorExit:
            # 生成器被关闭（如服务端主动收流）：当前任务未被取消，直接收尾
            await finalize_stream(
                self.user,
                self.db,
                message,
                run_record,
                status="failed",
                text=text,
                parts=parts,
                error="客户端断开连接",
                metrics={},
            )
            raise
        except asyncio.CancelledError:
            # 客户端断线：当前任务已处于取消上下文，直接 await 会被再次取消，
            # 因此把收尾交给独立任务，并用 shield 等待其完成
            task = asyncio.create_task(
                cleanup_interrupted(
                    self.user,
                    message.id,
                    run_record.run_id,
                    text,
                    parts,
                    "客户端断开连接",
                )
            )
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                pass
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("ChatStreamService: 流式运行失败 session=%s", session_id)
            status, error = "failed", str(exc)
            response = await finalize_stream(
                self.user,
                self.db,
                message,
                run_record,
                status=status,
                text=text,
                parts=parts,
                error=error,
                metrics={},
            )
            yield StreamEvent("error", {"message": error})
            yield end_event(response, status, {}, error)
            return
        finally:
            cancel_registry.release(run_id)

        response = await finalize_stream(
            self.user,
            self.db,
            message,
            run_record,
            status=status,
            text=text,
            parts=parts,
            error=error,
            metrics=metrics,
        )
        yield end_event(response, status, metrics, error)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @staticmethod
    def _build_agent(run_id: str) -> Any:
        """构造单 Agent（与 AgentService 同步路径保持一致）。"""
        from harness.agents.react_agent import ReActAgent
        from harness.platform.service.model_factory import (
            build_default_model,
            build_default_tools,
        )

        return ReActAgent(
            model=build_default_model(),
            tools=build_default_tools(),
            session_id=run_id,
        )

    async def _create_run(self, run_id: str, goal: str, session_id: str) -> AgentRun:
        """插入运行记录并置为 running。"""
        now = datetime.now(timezone.utc)
        record = AgentRun(
            run_id=run_id,
            session_id=session_id,
            tenant_id=self.user.tenant_id,
            user_id=self.user.user_id,
            mode="single",
            status="running",
            input=json.dumps({"goal": goal}, ensure_ascii=False),
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        return await self.runs.save(record)


__all__ = ["ChatStreamService", "StreamEvent"]
