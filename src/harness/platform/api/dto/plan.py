"""Plan 相关 DTO（POST /agents/plan、GET /plans）。"""

from __future__ import annotations

from typing import Any

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


class PlanSummary(BaseModel):
    """Plan 的对外摘要。"""

    plan_id: str
    goal: str
    steps: list[dict[str, Any]] = Field(default_factory=list)
    plan_hash: str = ""
    approved: bool = False
    status: str = "pending"
    created_at: str = ""
    updated_at: str = ""


class AgentPlanResponse(BaseModel):
    """POST /agents/plan 响应体。"""

    plan: PlanSummary


class PlanListResponse(BaseModel):
    """GET /plans 响应体。"""

    items: list[PlanSummary] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    size: int = 20


class AgentExecuteResponse(BaseModel):
    """POST /agents/{id}/execute 响应体。"""

    plan_id: str
    run_id: str
    status: str


class AgentStatusResponse(BaseModel):
    """GET /agents/{id}/status 响应体。"""

    run_id: str
    status: str
    output: str | None = None
    error: str | None = None


class AgentCancelResponse(BaseModel):
    """POST /agents/{id}/cancel 响应体。"""

    run_id: str
    status: str


__all__ = [
    "PlanStepInput",
    "AgentPlanRequest",
    "PlanSummary",
    "AgentPlanResponse",
    "PlanListResponse",
    "AgentExecuteResponse",
    "AgentStatusResponse",
    "AgentCancelResponse",
]
