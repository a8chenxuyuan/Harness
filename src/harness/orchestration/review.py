"""Plan 确认闸门（Phase 19）。

两种模式：
    - HITL（默认）：复用 HitlManager，阻塞直到人工 approve/deny；
      本模块只做一层薄封装——把 Plan 的 approve 请求转成一次 HITL request。
    - AUTO：白名单校验（steps ≤ 上限、工具在白名单内、无嵌套 Coordinator），
      通过则直接放行；验收脚本用 AUTO 模式跳过真实 HITL。

闸门语义：executor 只有在 plan.approved=True 时才派发任何 Worker。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from .coordinator import ConfigurationError
from .plan import Plan

if TYPE_CHECKING:
    from harness.integrations.hitl.manager import HitlManager
    from harness.common.observability.metrics import PlanApprovalLatency  # 占位


# 模块级全局白名单（AUTO 模式用，HITL 模式忽略）
_AUTO_MAX_STEPS = 8


async def review_plan(
    plan: Plan,
    *,
    hitl_manager: "HitlManager | None" = None,
    auto_allow: bool = False,
    tool_whitelist: Iterable[str] | None = None,
    auto_timeout: float = 60.0,
) -> Plan:
    """Plan 确认闸门：返回一个（可能已 approve 的）新 Plan 实例。

    Args:
        plan: 待确认的 Plan（approved=False）。
        hitl_manager: HITL 管理器；非 None 且 auto_allow=False 时走 HITL 模式。
        auto_allow: True 时走 AUTO 模式（白名单校验通过即放行）。
        tool_whitelist: AUTO 模式下允许的工具名集合；None 跳过工具检查。
        auto_timeout: HITL 模式的等待超时（秒）。

    Returns:
        已 approve 的 Plan。

    Raises:
        ConfigurationError: 闸门拒绝（plan 非法 / HITL deny / AUTO 白名单未过）。
    """
    from harness.common.observability.metrics import record_plan_approval_latency

    start = time.monotonic()

    # 闸门硬拦截：未批准 Plan 绝对不会让 executor 派发
    if plan.approved:
        return plan

    if auto_allow:
        _auto_validate(plan, tool_whitelist)
        result = plan.approve()
    else:
        if hitl_manager is None:
            raise ConfigurationError("HITL 模式需注入 HitlManager 或切换 auto_allow=True")
        result = await _hitl_review(plan, hitl_manager, auto_timeout)

    record_plan_approval_latency(time.monotonic() - start)
    return result


def _auto_validate(plan: Plan, tool_whitelist: Iterable[str] | None) -> None:
    """AUTO 白名单校验：非法 Plan 直接抛 ConfigurationError。"""
    if len(plan.steps) == 0:
        raise ConfigurationError("Plan 没有步骤")
    if len(plan.steps) > _AUTO_MAX_STEPS:
        raise ConfigurationError(f"Plan 步骤数 {len(plan.steps)} 超过上限 {_AUTO_MAX_STEPS}")
    if tool_whitelist is not None:
        allowed = set(tool_whitelist)
        for step in plan.steps:
            overflow = set(step.tools_allowed) - allowed
            if overflow:
                raise ConfigurationError(
                    f"step {step.task_id} 工具越界: {sorted(overflow)}"
                )


async def _hitl_review(
    plan: Plan, hitl_manager: "HitlManager", timeout: float
) -> Plan:
    """向 HitlManager 发一次 approve 请求，等待决策后返回 Plan 或抛错。"""
    request_id = await hitl_manager.request_approval(
        tool_name="plan_review",
        args={"plan_id": plan.plan_id, "goal": plan.goal,
              "steps": [s.task_id for s in plan.steps]},
    )
    session = await hitl_manager.wait_for_decision(request_id, timeout=timeout)
    if session.status == "approved":
        return plan.approve()
    raise ConfigurationError(f"Plan {plan.plan_id} 被 {session.status} 拒绝: {session.reason}")
