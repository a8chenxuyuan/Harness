"""Agent 应用服务 — 把 HTTP 请求桥接到 Harness 底层编排引擎，并落库运行记录。

职责：
    - 每次运行写一条 ``agent_runs``（queued → running → succeeded/failed）
    - 传入 conversation_id 时，把用户输入与助手输出追加到 ``session_messages``
    - 把 AgentRunRequest 翻译成 CoordinatorAgent / ReActAgent 的调用
    - 不写 FastAPI 路由，不返回引擎内部对象给 Controller

调用链：
    Controller(agents.py) → AgentService.run() → orchestration.CoordinatorAgent.run()
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from harness.platform.api.exceptions import BizError
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.entity.agent_run import AgentRun
from harness.platform.repository.agent_run_repository import AgentRunRepository

log = logging.getLogger(__name__)


class AgentService:
    """Agent 运行用例的业务编排（运行记录持久化）。"""

    def __init__(self, user: UserInfo, db) -> None:
        self.user = user
        self.db = db
        self.runs = AgentRunRepository(db)

    async def run(
        self,
        *,
        goal: str,
        mode: str = "single",
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """运行 Agent（绑定链路上下文 + agent.run span 后转交内部实现）。"""
        from harness.common.observability.context import (
            bind_run_context,
            reset_run_context,
        )
        from harness.common.observability.tracing import start_span

        run_id = f"run-{uuid.uuid4().hex[:12]}"
        token = bind_run_context(
            tenant_id=self.user.tenant_id,
            user_id=self.user.user_id,
            session_id=conversation_id,
            run_id=run_id,
            mode=mode,
        )
        try:
            with start_span("agent.run", {"mode": mode}) as span:
                result = await self._run_inner(
                    goal=goal,
                    mode=mode,
                    conversation_id=conversation_id,
                    run_id=run_id,
                )
                span.set_attribute("status", str(result.get("status") or ""))
                return result
        finally:
            reset_run_context(token)

    async def _run_inner(
        self,
        *,
        goal: str,
        mode: str = "single",
        conversation_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """运行 Agent 并持久化运行记录。

        Args:
            goal: 人类可读的目标描述。
            mode: "single" 直接跑单 Agent；"coordinator" 走 Plan→Review→Executor。
            conversation_id: 续跑时传已有会话 id；存在时会落对话消息。
            run_id: 预生成的运行 id（链路上下文需要提前绑定）。

        Returns:
            {"run_id", "status", "output", "metrics"} —— 正好是 AgentRunResponse 的字段。
        """
        run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
        # 配额检查：并发 / 当日消息 / 当日 token，超限直接 429 不创建运行记录
        from harness.platform.service.quota_service import QuotaService

        quota = QuotaService(self.db)
        await quota.ensure_available(self.user.tenant_id)
        await quota.record_run_started(self.user.tenant_id)

        record = await self._create_run(run_id, goal, mode, conversation_id)
        try:
            await self._append_user_message(conversation_id, goal)
        except BizError:
            await self._finish_run(record, status="failed", error="session not found")
            raise

        try:
            result = await self._execute(goal, mode, run_id)
        except Exception as exc:  # noqa: BLE001
            log.exception("AgentService: run failed")
            await self._finish_run(record, status="failed", error=str(exc))
            result = {
                "run_id": run_id,
                "status": "failed",
                "output": None,
                "metrics": {"error": str(exc)},
            }
        else:
            status = "succeeded" if result.get("status") == "success" else "failed"
            await self._finish_run(
                record,
                status=status,
                output=result.get("output"),
                metrics=result.get("metrics"),
            )
            await self._append_assistant_message(conversation_id, result.get("output"))

        await self._record_quota_usage(result, conversation_id)
        return result

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    async def _execute(self, goal: str, mode: str, run_id: str) -> dict[str, Any]:
        """按模式选择引擎执行。"""
        if mode == "coordinator":
            return await self._run_coordinator(goal, run_id)
        return await self._run_single(goal, run_id)

    async def _run_coordinator(self, goal: str, run_id: str) -> dict[str, Any]:
        """多 Agent 编排：Plan → Dispatch → Aggregate。"""
        from harness.platform.service.plan_service import PlanService

        coord = PlanService.build_coordinator()
        result = await coord.run(goal=goal)
        ok = bool(result.get("terminated"))
        outputs = result.get("outputs") or {}
        output = "\n".join(
            str(value) for value in outputs.values() if value
        ) if ok else None
        return {
            "run_id": run_id,
            "status": "success" if ok else "failed",
            "output": output,
            "metrics": {
                "total": result.get("total", 0),
                "done": result.get("done", 0),
                "failed": result.get("failed", 0),
                "wall_seconds": result.get("wall_seconds", 0),
                "prompt_tokens": result.get("prompt_tokens", 0),
                "completion_tokens": result.get("completion_tokens", 0),
                "total_tokens": result.get("total_tokens", 0),
                "cache_read_tokens": result.get("cache_read_tokens", 0),
            },
        }

    async def _run_single(self, goal: str, run_id: str) -> dict[str, Any]:
        """单 Agent 直接执行。"""
        from harness.agents.react_agent import ReActAgent
        from harness.platform.service.model_factory import (
            build_default_model,
            build_default_tools,
        )

        agent = ReActAgent(
            model=build_default_model(),
            tools=build_default_tools(),
            session_id=run_id,
        )
        state = await agent.run(goal)
        model_error = (
            state.stop_reason
            if state.stop_reason and state.stop_reason.startswith("model_error")
            else None
        )
        return {
            "run_id": run_id,
            "status": "failed" if model_error else "success",
            "output": state.last_response_text or None,
            "metrics": state.metrics,
        }

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    async def _create_run(
        self, run_id: str, goal: str, mode: str, conversation_id: str | None
    ) -> AgentRun:
        """插入运行记录并置为 running。"""
        now = datetime.now(timezone.utc)
        record = AgentRun(
            run_id=run_id,
            session_id=conversation_id,
            tenant_id=self.user.tenant_id,
            user_id=self.user.user_id,
            mode=mode,
            status="running",
            input=json.dumps({"goal": goal}, ensure_ascii=False),
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        return await self.runs.save(record)

    async def _finish_run(
        self,
        record: AgentRun,
        *,
        status: str,
        output: str | None = None,
        error: str | None = None,
        metrics: Any = None,
    ) -> None:
        """写终态：状态、输出、错误、token 用量、结束时间。"""
        now = datetime.now(timezone.utc)
        record.status = status
        record.output = output
        record.error = error
        record.token_usage = json.dumps(
            metrics if isinstance(metrics, dict) else {}, ensure_ascii=False
        )
        record.finished_at = now
        record.updated_at = now
        await self.runs.save(record)

    async def _record_quota_usage(
        self, result: dict[str, Any], conversation_id: str | None
    ) -> None:
        """累加当日用量（失败只记录日志，不影响运行结果）。"""
        try:
            metrics = result.get("metrics") or {}
            tokens = int(metrics.get("total_tokens") or 0)
            messages = 0
            if conversation_id:
                messages = 2 if result.get("output") else 1
            from harness.platform.service.quota_service import QuotaService

            await QuotaService(self.db).record_usage(
                self.user.tenant_id, messages=messages, tokens=tokens
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("AgentService: 配额用量累加失败: %s", exc)

    async def _append_user_message(
        self, conversation_id: str | None, goal: str
    ) -> None:
        """把用户输入追加进会话（会话不存在/不属于当前用户时抛 404）。"""
        if not conversation_id:
            return
        from harness.platform.api.dto.message_dto import MessageCreateRequest
        from harness.platform.service.message_service import MessageService

        await MessageService(self.user, self.db).append_message(
            conversation_id,
            MessageCreateRequest(role="user", text=goal),
        )

    async def _append_assistant_message(
        self, conversation_id: str | None, output: str | None
    ) -> None:
        """把助手最终回答追加进会话（无输出时跳过）。"""
        if not conversation_id or not output:
            return
        from harness.platform.api.dto.message_dto import MessageCreateRequest
        from harness.platform.service.message_service import MessageService

        try:
            await MessageService(self.user, self.db).append_message(
                conversation_id,
                MessageCreateRequest(role="assistant", text=output),
            )
        except Exception:  # noqa: BLE001 — 落消息失败不影响运行结果返回
            log.warning("AgentService: 助手消息落库失败 session=%s", conversation_id)
