"""Plan 域入参（DTO）。

只放请求模型；响应模型在 ``api.vo.plan``。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlanStepInput(BaseModel):
    """创建 Plan 时的单个步骤入参。"""

    task_id: str = Field(default="", max_length=64)
    goal: str = Field(..., min_length=1, max_length=2000)
    input: str = Field(default="", max_length=8000)
    worker: str | None = Field(default=None, max_length=64)
    depends_on: list[str] = Field(default_factory=list)
    tools_allowed: list[str] = Field(default_factory=list)
    max_steps: int = Field(default=20, ge=1, le=100)


class AgentPlanRequest(BaseModel):
    """POST /api/v1/agents/plan 请求体。"""

    goal: str = Field(..., min_length=1, max_length=4000)
    steps: list[PlanStepInput] = Field(..., min_length=1, description="显式步骤（不调 LLM）")


__all__ = ["PlanStepInput", "AgentPlanRequest"]
