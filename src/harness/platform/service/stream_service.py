"""流式对话服务 — 把 Agent 的流式事件转成 SSE 领域事件并增量落库。

职责：
    - 校验会话归属，落用户消息与 assistant 占位消息（status=streaming）
    - 消费 ``ReActAgent.run_stream`` 的 LoopStreamEvent，转成 StreamEvent
    - 节流把文本 / 工具块增量写回 ``session_messages``
    - 正常结束置 ``completed``，异常或客户端断线置 ``failed``（保留已生成内容）
    - 维护 ``agent_runs`` 状态与 token 用量

事件协议（SSE 的 event 名）：
    - ``message_start``  {run_id, message_id, session_id, seq}
    - ``part_delta``     {delta}
    - ``tool_call``      {status: start|end, calls?|results?}
    - ``message_end``    {status, message, metrics, error}
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
from harness.platform.api.vo.message_vo import MessageResponse
from harness.platform.entity.agent_run import AgentRun
from harness.platform.repository.agent_run_repository import AgentRunRepository
from harness.platform.service.message_service import MessageService
from harness.platform.service.stream_events import (
    StreamEvent,
    append_text_part,
    tool_part,
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

        try:
            agent = self._build_agent(run_id)
            async for event in agent.run_stream(goal):
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
            if agent.state is not None:
                metrics = dict(agent.state.metrics)
        except GeneratorExit:
            # 生成器被关闭（如服务端主动收流）：当前任务未被取消，直接收尾
            await self._finalize(
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
                self._cleanup_interrupted(
                    message.id, run_record.run_id, text, parts, "客户端断开连接"
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
            response = await self._finalize(
                message,
                run_record,
                status=status,
                text=text,
                parts=parts,
                error=error,
                metrics={},
            )
            yield StreamEvent("error", {"message": error})
            yield self._end_event(response, status, {}, error)
            return

        response = await self._finalize(
            message,
            run_record,
            status=status,
            text=text,
            parts=parts,
            error=error,
            metrics=metrics,
        )
        yield self._end_event(response, status, metrics, error)

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

    async def _finalize(
        self,
        message,
        record: AgentRun,
        *,
        status: str,
        text: str,
        parts: list[dict],
        error: str | None,
        metrics: dict[str, int],
    ) -> MessageResponse:
        """落消息终态 + 运行终态，返回最终消息快照。"""
        response = await self.messages.finish_streaming_message(
            message, text=text, parts=parts, status=status
        )
        now = datetime.now(timezone.utc)
        record.status = "succeeded" if status == "completed" else "failed"
        record.output = text or None
        record.error = error
        record.token_usage = json.dumps(metrics or {}, ensure_ascii=False)
        record.finished_at = now
        record.updated_at = now
        try:
            await self.runs.save(record)
        except Exception:  # noqa: BLE001 — 运行记录失败不影响消息终态
            log.exception("ChatStreamService: 运行记录落库失败 run=%s", record.run_id)
        return response

    async def _cleanup_interrupted(
        self,
        message_id: str,
        run_id: str,
        text: str,
        parts: list[dict],
        error: str,
    ) -> None:
        """断线收尾：用独立 DB session 把消息与运行记录置为 failed。

        断线时当前任务处于取消上下文，原 session 的后续 await 会被再次取消，
        因此必须新开连接、在独立任务中完成收尾。
        """
        from harness.platform.infra.engine import get_session_factory

        try:
            factory = get_session_factory()
            async with factory() as session:
                messages = MessageService(self.user, session)
                message = await messages.messages.get(message_id)
                if message is not None:
                    await messages.finish_streaming_message(
                        message, text=text, parts=parts, status="failed"
                    )
                runs = AgentRunRepository(session)
                record = await runs.get(run_id)
                if record is None:
                    return
                now = datetime.now(timezone.utc)
                record.status = "failed"
                record.output = text or None
                record.error = error
                record.finished_at = now
                record.updated_at = now
                await runs.save(record)
        except Exception:  # noqa: BLE001 — 收尾失败只记日志，避免任务异常逃逸
            log.exception("ChatStreamService: 断线收尾失败 message=%s", message_id)

    @staticmethod
    def _end_event(
        response: MessageResponse,
        status: str,
        metrics: dict[str, int],
        error: str | None,
    ) -> StreamEvent:
        """组装 message_end 事件（携带最终消息快照）。"""
        return StreamEvent(
            "message_end",
            {
                "status": status,
                "message": response.model_dump(mode="json"),
                "metrics": metrics,
                "error": error,
            },
        )


__all__ = ["ChatStreamService", "StreamEvent"]
