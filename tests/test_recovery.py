"""启动恢复测试（W3-KERN-01）。

覆盖：
    - running 运行 / streaming 消息 / running 计划 → 终态
    - 已是终态的记录不受影响
    - 重复执行幂等（第二次影响行数为 0）
"""

from __future__ import annotations

from harness.platform.entity.agent_run import AgentRun
from harness.platform.entity.plan import PlanRecord
from harness.platform.entity.session_message import SessionMessage
from harness.platform.service.recovery_service import RecoveryService


async def test_recovery_converges_transient_states(db_session) -> None:
    """只收敛中间态，终态记录保持不变。"""
    db_session.add_all(
        [
            AgentRun(run_id="run-running", tenant_id="t1", user_id="u1", status="running"),
            AgentRun(run_id="run-done", tenant_id="t1", user_id="u1", status="succeeded"),
            SessionMessage(
                id="msg-streaming",
                session_id="s1",
                tenant_id="t1",
                role="assistant",
                status="streaming",
            ),
            SessionMessage(
                id="msg-completed",
                session_id="s1",
                tenant_id="t1",
                role="assistant",
                status="completed",
            ),
            PlanRecord(plan_id="plan-running", tenant_id="t1", user_id="u1", status="running"),
            PlanRecord(plan_id="plan-done", tenant_id="t1", user_id="u1", status="done"),
        ]
    )
    await db_session.commit()

    counts = await RecoveryService(db_session).recover()
    assert counts == {
        "runs_interrupted": 1,
        "messages_failed": 1,
        "plans_interrupted": 1,
    }

    db_session.expire_all()
    assert (await db_session.get(AgentRun, "run-running")).status == "interrupted"
    assert (await db_session.get(AgentRun, "run-done")).status == "succeeded"
    assert (await db_session.get(SessionMessage, "msg-streaming")).status == "failed"
    assert (await db_session.get(SessionMessage, "msg-completed")).status == "completed"
    assert (await db_session.get(PlanRecord, "plan-running")).status == "interrupted"
    assert (await db_session.get(PlanRecord, "plan-done")).status == "done"


async def test_recovery_is_idempotent(db_session) -> None:
    """重复执行不再命中任何记录。"""
    db_session.add(
        AgentRun(run_id="run-x", tenant_id="t1", user_id="u1", status="running")
    )
    await db_session.commit()

    first = await RecoveryService(db_session).recover()
    second = await RecoveryService(db_session).recover()

    assert first["runs_interrupted"] == 1
    assert second == {
        "runs_interrupted": 0,
        "messages_failed": 0,
        "plans_interrupted": 0,
    }
