"""PlanService — Plan 创建 / 持久化 / 后台执行编排（Phase 23）。

职责：
    - 把显式 steps 转成 TaskSpec，经 PlanAgent 产出 Plan（不调 LLM）
    - 落库到 plans 表（方案 A：sessions 只存元数据，Plan 单独建表）
    - 后台执行：构造 Coordinator + PlanExecutor，执行完回写状态

模型凭据缺失时 execute 会明确失败，不做「假装成功」的降级。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from harness.platform.api.dto.auth import UserInfo
from harness.platform.models.plan import PlanRecord
from harness.platform.repository.plan_repo import PlanRepository

log = logging.getLogger(__name__)


class PlanService:
    """计划相关业务编排。"""

    def __init__(self, session, user: UserInfo) -> None:
        self.session = session
        self.user = user
        self.repo = PlanRepository(session)

    # ------------------------------------------------------------------
    # 创建 / 查询
    # ------------------------------------------------------------------

    async def create_plan(self, goal: str, steps: list[dict[str, Any]]) -> PlanRecord:
        """根据显式 steps 创建 Plan 并落库（approved=False）。

        Args:
            goal: 总目标。
            steps: 步骤字典列表（来自 ``PlanStepInput.model_dump()``）。

        Returns:
            已持久化的 PlanRecord。
        """
        from harness.orchestration.plan import PlanAgent
        from harness.orchestration.task import TaskSpec

        specs = [
            TaskSpec(
                task_id=str(item.get("task_id") or f"t{i + 1}"),
                goal=str(item["goal"]),
                input=str(item.get("input", "")),
                worker=item.get("worker"),
                depends_on=tuple(item.get("depends_on") or ()),
                tools_allowed=tuple(item.get("tools_allowed") or ()),
                max_steps=int(item.get("max_steps") or 20),
            )
            for i, item in enumerate(steps)
        ]
        # 显式 steps 路径不会触达 self.model，所以 model=None 是安全的。
        agent = PlanAgent(model=None)  # type: ignore[arg-type]
        plan = await agent.plan(goal, specs)

        record = PlanRecord(
            plan_id=plan.plan_id,
            tenant_id=self.user.tenant_id,
            user_id=self.user.user_id,
            goal=plan.goal,
            steps_json=json.dumps(
                [s.model_dump() for s in plan.steps], ensure_ascii=False, default=list
            ),
            plan_text=plan.plan_text,
            plan_hash=plan.plan_hash,
            approved=False,
            status="pending",
        )
        return await self.repo.save(record)

    async def get(self, plan_id: str) -> PlanRecord:
        """按租户隔离取 Plan；不存在抛 BizError(404)。"""
        from harness.platform.api.exceptions import BizError

        record = await self.repo.get_by_id(self.user.tenant_id, plan_id)
        if record is None:
            raise BizError(404, f"plan {plan_id} not found")
        return record

    async def list_plans(self, page: int, size: int) -> tuple[list[PlanRecord], int]:
        """分页列出当前租户的计划。"""
        offset = (page - 1) * size
        records = await self.repo.list_by_tenant(
            self.user.tenant_id, offset=offset, limit=size
        )
        total = await self.repo.count_by_tenant(self.user.tenant_id)
        return records, total

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    async def execute(self, record: PlanRecord) -> str:
        """同步执行（在后台协程内调用），返回 JSON 字符串结果。

        审批闸门：executor 要求 approved=True；Phase 23 的 execute 接口
        本身即「人工点击执行」，等价于批准，故这里自动 approve。
        """
        from harness.orchestration.executor import PlanExecutor

        await self.repo.update_status(record, "running")
        plan = self.record_to_plan(record)
        if not plan.approved:
            plan = plan.approve()

        coordinator = self.build_coordinator()
        result = await PlanExecutor(coordinator).run(plan)
        status = "done" if result.success else "failed"
        await self.repo.update_status(record, status)
        return json.dumps(
            {
                "plan_id": record.plan_id,
                "success": result.success,
                "failed_at": result.failed_at,
                "steps": [
                    {
                        "task_id": r.task_id,
                        "status": r.status.value,
                        "output": (r.output or "")[:500],
                        "error": r.error,
                    }
                    for r in result.results
                ],
            },
            ensure_ascii=False,
        )

    # ------------------------------------------------------------------
    # 构造
    # ------------------------------------------------------------------

    @staticmethod
    def record_to_plan(record: PlanRecord):
        """把 PlanRecord 反序列化为 orchestration.Plan。"""
        from harness.orchestration.plan import Plan
        from harness.orchestration.task import TaskSpec

        try:
            raw_steps = json.loads(record.steps_json or "[]")
        except json.JSONDecodeError:
            raw_steps = []
        steps = tuple(TaskSpec(**s) for s in raw_steps)
        return Plan(
            plan_id=record.plan_id,
            goal=record.goal,
            steps=steps,
            plan_text=record.plan_text,
            plan_hash=record.plan_hash,
            approved=record.approved,
        )

    @staticmethod
    def build_coordinator():
        """按当前 Settings 构造 Coordinator（模型凭据缺失时明确报错）。"""
        from harness.common.config.settings import Settings
        from harness.core.model.openai_compat import OpenAICompat
        from harness.core.permission.engine import PermissionEngine
        from harness.core.permission.mode import PermissionMode
        from harness.core.tool.builtin import (
            BashTool,
            HttpGetTool,
            ReadFileTool,
            WriteFileTool,
        )
        from harness.core.tool.registry import ToolRegistry
        from harness.orchestration.coordinator import CoordinatorAgent, WorkerSpec

        settings = Settings()
        if not settings.model.has_credentials():
            raise RuntimeError(
                "模型凭据未配置（MODEL__API_KEY / HARNESS_MODEL__API_KEY），无法执行 Plan"
            )

        model = OpenAICompat(
            base_url=settings.model.base_url or "https://api.deepseek.com/v1",
            api_key=settings.model.api_key,
            model=settings.model.model or "deepseek-chat",
        )
        tools = ToolRegistry()
        for tool in (ReadFileTool(), WriteFileTool(), BashTool(), HttpGetTool()):
            tools.register(tool)

        return CoordinatorAgent(
            model=model,
            tools=tools,
            permission_engine=PermissionEngine(PermissionMode.DEFAULT),
            worker_specs=[
                WorkerSpec(
                    name="worker",
                    system_prompt="你是 harness 计划执行 Worker。按步骤目标完成任务并输出结论。",
                    tools_allowed=(),
                )
            ],
        )


__all__ = ["PlanService"]
