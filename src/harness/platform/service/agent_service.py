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
        """运行 Agent 并持久化运行记录。

        Args:
            goal: 人类可读的目标描述。
            mode: "single" 直接跑单 Agent；"coordinator" 走 Plan→Review→Executor。
            conversation_id: 续跑时传已有会话 id；存在时会落对话消息。

        Returns:
            {"run_id", "status", "output", "metrics"} —— 正好是 AgentRunResponse 的字段。
        """
        run_id = f"run-{uuid.uuid4().hex[:12]}"
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
        state = await agent.run_loop(goal)
        return {
            "run_id": run_id,
            "status": "success" if not getattr(state, "error", None) else "failed",
            "output": getattr(state, "final_answer", None),
            "metrics": getattr(state, "metrics", None),
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
