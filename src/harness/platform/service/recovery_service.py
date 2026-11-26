"""启动恢复服务（W3-KERN-01）。

进程重启后，内存态运行（run_registry / 后台 task / SSE 流）全部丢失，
数据库里可能残留以下「中间态」，必须统一收尾，否则前端会一直轮询：

    agent_runs.status      running   → interrupted
    session_messages.status streaming → failed
    plans.status           running   → interrupted

恢复动作幂等：重复执行只会命中仍停留在中间态的记录，终态记录不受影响。
"""

from __future__ import annotations

import logging

from harness.platform.repository.agent_run_repository import AgentRunRepository
from harness.platform.repository.plan_repository import PlanRepository
from harness.platform.repository.session_message_repository import (
    SessionMessageRepository,
)

log = logging.getLogger(__name__)

RUN_INTERRUPTED_ERROR = "服务重启，运行被中断（interrupted）"


class RecoveryService:
    """把重启前遗留的中间态记录收敛到终态。"""

    def __init__(self, session) -> None:
        self.session = session
        self.runs = AgentRunRepository(session)
        self.messages = SessionMessageRepository(session)
        self.plans = PlanRepository(session)

    async def recover(self) -> dict[str, int]:
        """执行三类恢复，返回各自影响行数。"""
        counts = {
            "runs_interrupted": await self.runs.mark_statuses(
                "running", "interrupted", error=RUN_INTERRUPTED_ERROR
            ),
            "messages_failed": await self.messages.mark_statuses(
                "streaming", "failed"
            ),
            "plans_interrupted": await self.plans.mark_statuses(
                "running", "interrupted"
            ),
        }
        return counts


async def recover_interrupted() -> dict[str, int]:
    """开独立 session 执行启动恢复（供 app lifespan 调用）。

    任何异常只记录 warn，不阻断服务启动；正常返回影响行数字典。
    """
    try:
        from harness.platform.infra.engine import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            counts = await RecoveryService(session).recover()
    except Exception as exc:  # noqa: BLE001 — 恢复失败不能阻断启动
        log.warning("recovery: 启动恢复失败（可忽略）: %s", exc)
        return {}

    total = sum(counts.values())
    if total:
        log.warning("recovery: 收敛重启遗留中间态 %s", counts)
    else:
        log.info("recovery: 无遗留中间态")
    return counts


__all__ = ["RecoveryService", "recover_interrupted", "RUN_INTERRUPTED_ERROR"]
