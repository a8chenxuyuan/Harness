"""Plan 模型与 PlanAgent（Phase 19）。

铁律（roadmap 0.3）：Plan 原文一旦批准，后续 replan 只能追加
replan entry，绝不能改写 steps。Plan 文本本身是稳定前缀的一部分——
同一 Plan 的多个步骤执行时 worker_prefix_stable_rounds 应连续。
"""

from __future__ import annotations

import hashlib
import uuid
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from .task import TaskSpec

if TYPE_CHECKING:
    from harness.core.model.base import Model


class ReplanEntry(BaseModel):
    """一次计划修订的追加条目（不改原 Plan 的 step，只记录修订意图）。

    Attributes:
        from_step: 触发修订的失败 step 序号（0-based）。
        reason: 修订原因（step.output / error 摘要）。
        revised_steps: 修订后的完整后续步骤（替换原 Plan steps[from_step+1:]）。
        plan_text_snapshot: 修订时 Plan 原文的哈希，保证审计可追溯。
    """

    model_config = ConfigDict(frozen=True)

    from_step: int
    reason: str
    revised_steps: tuple[TaskSpec, ...]
    plan_text_snapshot: str


class Plan(BaseModel):
    """一次可执行计划（frozen，批准后 immutable）。

    Attributes:
        plan_id: 计划唯一标识。
        goal: 总目标（与 Coordinator 的 goal 一致）。
        steps: TaskSpec 列表，depends_on 走 Coordinator 派发。
        expected_outputs: 每步产物预期（用于 executor 校验）；None 跳过校验。
        replan_entries: 追加式修订条目列表（不改 steps，仅记录修订历史）。
        plan_text: LLM 产出的原始计划文本（稳定前缀的一部分，用于缓存与审计）。
        plan_hash: plan_text 的 sha256（approved 后固定不变）。
        approved: 是否已过 review 闸门；False 时 executor 拒绝派发。
    """

    model_config = ConfigDict(frozen=True)

    plan_id: str
    goal: str
    steps: tuple[TaskSpec, ...]
    expected_outputs: tuple[str | None, ...] = ()
    replan_entries: tuple[ReplanEntry, ...] = ()
    plan_text: str = ""
    plan_hash: str = ""
    approved: bool = False

    # --- 便捷查询 -------------------------------------------------------------

    def with_revision(
        self, entry: ReplanEntry, revised_steps: tuple[TaskSpec, ...]
    ) -> "Plan":
        """返回一个新 Plan：追加 replan entry，原 steps 从失败步骤起换成 revised_steps。

        这是**唯一**允许修改 Plan steps 的入口——原 Plan 本身保持 immutable，
        修订产生一个新 Plan 实例；plan_hash 因 plan_text 不变，自然继承。
        """
        new_steps = list(self.steps[: entry.from_step + 1]) + list(revised_steps)
        return self.model_copy(
            update={
                "steps": tuple(new_steps),
                "replan_entries": self.replan_entries + (entry,),
            }
        )

    def approve(self) -> "Plan":
        """闸门放行：把 approved 置 True。"""
        return self.model_copy(update={"approved": True})


class PlanAgent:
    """跑一次 LLM 调用产出 Plan 的轻量 Agent（不跑完整 ReAct 循环）。

    设计取舍：
        - 计划文本作为稳定前缀——用固定 system_prompt + Goal 构成前缀，
          相同 Goal 多次调用直接命中供应商缓存（不用完整 run_loop 的 ReAct）。
        - LLM 输出必须是合法 JSON；否则抛 ConfigurationError（fail-fast）。
    """

    def __init__(self, *, model: "Model") -> None:
        self.model = model

    async def plan(
        self,
        goal: str,
        steps: list[TaskSpec] | None = None,
        expected_outputs: list[str | None] | None = None,
    ) -> Plan:
        """产出 Plan；显式传入 steps 则跳过 LLM。

        Args:
            goal: 总目标。
            steps: 显式拆解（P19 验收时可脚本化传入，跳过 LLM 不确定性）。
            expected_outputs: 每步产物预期。

        Returns:
            未批准的 Plan（approved=False，等 Review 闸门）。

        Raises:
            ConfigurationError: LLM 拆解不是合法 JSON。
        """
        if steps is not None:
            text = _make_fixed_plan_text(goal, steps)
            return _build_plan(goal, steps, expected_outputs, text)

        from harness.common.message.helpers import system_message, user_message
        from harness.core.model.types import GenerateOptions
        from .coordinator import ConfigurationError

        prompt = (
            "你是计划代理。把总目标拆成 3-6 个带顺序的任务，只输出 JSON 数组，"
            "每个元素含 task_id/goal/input/worker/depends_on 字段，不要输出其他内容。"
        )
        response = await self.model.generate(
            [system_message(prompt), user_message(goal)], [], GenerateOptions()
        )
        text = response.text
        import re
        match = re.search(r"[\[{].*[\]}]", text, re.DOTALL)
        try:
            items = __import__("json").loads(match.group(0) if match else text)
        except Exception as exc:  # noqa: BLE001
            raise ConfigurationError(f"Plan LLM 输出非法 JSON: {text[:200]}") from exc

        steps_list = [
            TaskSpec(
                task_id=str(it.get("task_id", f"t{i+1}")),
                goal=str(it.get("goal", "")),
                input=str(it.get("input", "")),
                worker=it.get("worker"),
                depends_on=tuple(it.get("depends_on", [])),
            )
            for i, it in enumerate(items)
        ]
        return _build_plan(goal, steps_list, expected_outputs, text)


# ---------------------------------------------------------------------------
# 模块级纯函数
# ---------------------------------------------------------------------------


def _make_fixed_plan_text(goal: str, steps: list[TaskSpec]) -> str:
    """显式 steps 的情况下也构造一份 plan_text（前缀一致性 & 审计）。"""
    return f"GOAL: {goal}\n" + "\n".join(
        f"- [{s.task_id}] {s.goal} (input={s.input!r})" for s in steps
    )


def _build_plan(
    goal: str,
    steps: list[TaskSpec],
    expected_outputs: list[str | None] | None,
    plan_text: str,
) -> Plan:
    plan_hash = "sha256:" + hashlib.sha256(plan_text.encode("utf-8")).hexdigest()
    return Plan(
        plan_id=f"plan-{uuid.uuid4().hex[:8]}",
        goal=goal,
        steps=tuple(steps),
        expected_outputs=tuple(expected_outputs or [None] * len(steps)),
        plan_text=plan_text,
        plan_hash=plan_hash,
    )
