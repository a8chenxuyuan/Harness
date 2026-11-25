"""Agent 应用服务 — 把 HTTP 请求桥接到 Harness 底层编排引擎。

职责：
    - 把 AgentRunRequest 翻译成 CoordinatorAgent / ReActAgent 的调用
    - 收集引擎返回的 status / output / metrics，组装成 AgentRunResponse
    - 不写 FastAPI 路由，不返回引擎内部对象给 Controller

调用链：
    Controller(agents.py) → AgentService.run() → orchestration.CoordinatorAgent.run()
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

log = logging.getLogger(__name__)


class AgentService:
    """Agent 运行用例的业务编排。"""

    def __init__(self) -> None:
        # Phase 22: self.session_repo = SessionRepository(db_session)
        pass

    async def run(
        self,
        *,
        goal: str,
        mode: str = "single",
        conversation_id: str | None = None,
        user_id: str = "",
        tenant_id: str = "",
    ) -> dict[str, Any]:
        """运行 Agent。

        Args:
            goal: 人类可读的目标描述。
            mode: "single" 直接跑单 Agent；"coordinator" 走 Plan→Review→Executor。
            conversation_id: 续跑时传已有会话 id。
            user_id: 调用者 id（审计用）。
            tenant_id: 租户隔离。

        Returns:
            {"run_id", "status", "output", "metrics"} —— 正好是 AgentRunResponse 的字段。
        """
        if mode == "coordinator":
            return await self._run_coordinator(goal, conversation_id, user_id, tenant_id)
        return await self._run_single(goal, conversation_id, user_id, tenant_id)

    # ------------------------------------------------------------------
    # Coordinator 模式：Plan → Review → Execute
    # ------------------------------------------------------------------

    async def _run_coordinator(
        self,
        goal: str,
        conversation_id: str | None,
        user_id: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        """多 Agent 编排完整链路。"""
        run_id = conversation_id or f"coord-{tenant_id}-{uuid.uuid4().hex[:8]}"

        try:
            from harness.orchestration import CoordinatorAgent
            coord = CoordinatorAgent(session_id=run_id)
            result = coord.run(goal=goal)
            return {
                "run_id": run_id,
                "status": result.get("status", "unknown"),
                "output": result.get("output"),
                "metrics": result.get("metrics"),
            }
        except Exception as exc:  # noqa: BLE001
            log.exception("AgentService: coordinator run failed")
            return {
                "run_id": run_id,
                "status": "failed",
                "output": None,
                "metrics": {"error": str(exc)},
            }

    # ------------------------------------------------------------------
    # Single 模式：直接跑 ReActAgent
    # ------------------------------------------------------------------

    async def _run_single(
        self,
        goal: str,
        conversation_id: str | None,
        user_id: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        """单 Agent 直接执行。"""
        run_id = conversation_id or f"agent-{tenant_id}-{uuid.uuid4().hex[:8]}"

        try:
            from harness.agents.react_agent import ReActAgent
            agent = ReActAgent(session_id=run_id)
            state = await agent.run_loop(goal)
            return {
                "run_id": run_id,
                "status": "success" if not getattr(state, "error", None) else "failed",
                "output": getattr(state, "final_answer", None),
                "metrics": getattr(state, "metrics", None),
            }
        except Exception as exc:  # noqa: BLE001
            log.exception("AgentService: single run failed")
            return {
                "run_id": run_id,
                "status": "failed",
                "output": None,
                "metrics": {"error": str(exc)},
            }
