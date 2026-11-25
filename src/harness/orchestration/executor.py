"""PlanExecutor：逐步派发 + 产物校验 + 失败回退（Phase 19）。

职责边界：
    - 只走**串行逐步**派发（plan steps 有顺序语义），不走 topo_waves 并发——
      step_i 依赖 step_{i-1} 产出；replan 产生新 Plan 后从失败步重新开始。
    - 每步派发调用 Coordinator._execute_one（复用 P18 的 Worker 派发管道），
      不重写执行逻辑。
    - 闸门铁律：plan.approved=False 直接抛 ConfigurationError，绝不派发。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .coordinator import ConfigurationError, CoordinatorAgent
from .plan import Plan
from .task import TaskResult, TaskStatus

if TYPE_CHECKING:
    from .replan import ReplanHandler

log = logging.getLogger(__name__)


class PlanExecutionResult:
    """一次 PlanExecutor.run 的完整结果（frozen）。

    Attributes:
        plan: 最终 Plan（可能已追加 replan entry）。
        results: 各 step 的 TaskResult，按执行顺序。
        success: 全部 step DONE 则 True。
        failed_at: 失败 step 序号（0-based）；全部成功则 None。
        replan_count: 执行期间触发的 replan 次数。
    """

    def __init__(
        self,
        plan: Plan,
        results: list[TaskResult],
        success: bool,
        failed_at: int | None,
        replan_count: int,
    ) -> None:
        self.plan = plan
        self.results = results
        self.success = success
        self.failed_at = failed_at
        self.replan_count = replan_count


class PlanExecutor:
    """按已批准 Plan 逐步派发的执行者。

    Attributes:
        coordinator: 复用 P18 的 Coordinator（持有 Worker 池）。
        replan_handler: 可选的 replan 处理器；注入则失败自动 replan 后重试。
        max_replans: 单次执行内最多 replan 次数（防无限循环）。
    """

    def __init__(
        self,
        coordinator: CoordinatorAgent,
        replan_handler: "ReplanHandler | None" = None,
        max_replans: int = 2,
    ) -> None:
        self.coordinator = coordinator
        self.replan_handler = replan_handler
        self.max_replans = max_replans

    async def run(self, plan: Plan) -> PlanExecutionResult:
        """执行 plan；未批准直接拒绝，失败可 replan 后继续。

        Args:
            plan: 必须已 approve 的 Plan。

        Returns:
            PlanExecutionResult（含最终 Plan + 全量结果 + 终止判定）。
        """
        if not plan.approved:
            raise ConfigurationError(
                f"Plan {plan.plan_id} 未过 review 闸门，禁止执行"
            )

        plan_ref = plan
        results: list[TaskResult] = []
        replan_count = 0
        idx = 0

        while idx < len(plan_ref.steps):
            step = plan_ref.steps[idx]
            log.info("[plan %s] step %d=%s dispatch", plan_ref.plan_id, idx, step.task_id)
            result = await self.coordinator.execute_single_task(step)
            results.append(result)

            if result.status == TaskStatus.DONE and self._validate_expected(
                result, plan_ref.expected_outputs[idx] if idx < len(plan_ref.expected_outputs) else None
            ):
                idx += 1
                continue

            # 失败：尝试 replan
            if replan_count < self.max_replans and self.replan_handler is not None:
                log.warning("[plan %s] step %d 失败，触发 replan", plan_ref.plan_id, idx)
                plan_ref = await self.replan_handler.replan(
                    plan_ref, failed_step_idx=idx, failed_result=result
                )
                replan_count += 1
                # replan 后的 Plan 会替换失败步之后的 steps；从 idx 重新开始
                continue

            # 不可恢复的失败：终止
            return PlanExecutionResult(
                plan=plan_ref,
                results=results,
                success=False,
                failed_at=idx,
                replan_count=replan_count,
            )

        return PlanExecutionResult(
            plan=plan_ref,
            results=results,
            success=True,
            failed_at=None,
            replan_count=replan_count,
        )

    @staticmethod
    def _validate_expected(result: TaskResult, expected: str | None) -> bool:
        """把 result 与 expected_output 做轻量比对。

        策略（避免严格 JSON 结构匹配带来的脆）：
            - expected 为 None → 跳过校验（直接视为通过）。
            - expected 非空 → result.output 包含 expected 至少一个关键词片段通过。
        """
        if expected is None:
            return True
        if not result.output:
            return False
        # expected 里每个非空片段都应出现在 result.output 里
        keywords = [k.strip() for k in expected.split(",") if k.strip()]
        if not keywords:
            return True
        return all(k in result.output for k in keywords)
