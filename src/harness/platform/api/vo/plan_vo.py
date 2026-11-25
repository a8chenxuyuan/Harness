"""Plan 域出参（VO）。

请求模型在 ``api.dto.plan``。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
    """GET /plans 列表响应（分页）。"""

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
    "PlanSummary",
    "AgentPlanResponse",
    "PlanListResponse",
    "AgentExecuteResponse",
    "AgentStatusResponse",
    "AgentCancelResponse",
]
