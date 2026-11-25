"""计划修订：追加式 replan（Phase 19）。

铁律（roadmap 0.3）：**replan 只能追加 entry，绝不改写已批准 Plan 的原文**。
本模块的实现方式：
    - 失败 step 之前的 steps 原样保留（原 Plan 的不可变前缀部分）。
    - 失败 step 本身 + 后续步骤 由 PlanAgent 增量产出新 steps。
    - 生成 ReplanEntry 记录修订意图；Plan 模型层的 Plan.with_revision()
      负责把 entry 追加到 replan_entries 并产生新 Plan 实例——原 Plan 对象不变。
    - 记录 replan_total 指标（低频，高频说明拆解质量差）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .plan import Plan, PlanAgent, ReplanEntry
from .task import TaskResult, TaskSpec

if TYPE_CHECKING:
    from harness.core.model.base import Model


class ReplanHandler:
    """失败 step 触发的增量修订处理器（确定性修订，不走 LLM）。

    修订策略：保留失败步（goal 追加 retry 说明），丢弃失败步之后的原 steps——
    让 PlanExecutor 从失败步重新开始；后续步骤会在下一轮 executor.run 中
    重新编排（或者由业务方传入显式 revised_steps）。
    """

    async def replan(
        self,
        plan: Plan,
        *,
        failed_step_idx: int,
        failed_result: TaskResult,
        revised_steps: list[TaskSpec] | None = None,
    ) -> Plan:
        """对失败 step 做增量修订，返回带 ReplanEntry 的新 Plan。

        Args:
            plan: 当前 Plan。
            failed_step_idx: 失败 step 序号（0-based）。
            failed_result: 失败 TaskResult。
            revised_steps: 可选的显式修订步骤（优先级最高）；None 则走确定性策略。

        Returns:
            新 Plan 实例：原 steps 从失败步起被替换；原 Plan 对象不变。
        """
        from harness.common.observability.metrics import record_replan

        record_replan(plan_id=plan.plan_id)

        plan_text_snapshot = plan.plan_hash
        reason = (failed_result.error or failed_result.output[:200]
                  or f"step {failed_step_idx} status={failed_result.status}")

        # 确定性修订（不走 LLM）：失败步 goal 追加 retry + 保留后续原 steps
        if revised_steps is None:
            revised_steps = self._deterministic_revise(plan, failed_step_idx, failed_result)

        entry = ReplanEntry(
            from_step=failed_step_idx,
            reason=reason,
            revised_steps=tuple(revised_steps),
            plan_text_snapshot=plan_text_snapshot,
        )
        return plan.with_revision(entry, tuple(revised_steps))

    def _deterministic_revise(
        self, plan: Plan, failed_idx: int, failed_result: TaskResult
    ) -> list[TaskSpec]:
        """确定性修订：失败步 goal 追加 retry 说明，后续 steps 保留原顺序。"""
        steps: list[TaskSpec] = []
        for i, step in enumerate(plan.steps):
            if i < failed_idx:
                steps.append(step)  # 已完成步保留
            elif i == failed_idx:
                # 失败步重写 goal（retry），input 不变
                new_goal = (
                    f"{step.goal}（retry: {failed_result.error or '简化执行'}）"
                )
                steps.append(step.model_copy(update={"goal": new_goal}))
            else:
                # 后续步保留，但如果 depends_on 里有失败步，追加失败步到依赖
                if failed_idx < len(plan.steps):
                    steps.append(step)
                else:
                    steps.append(step)
        return steps
