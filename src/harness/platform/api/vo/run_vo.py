"""运行记录域出参（VO）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RunResponse(BaseModel):
    """单条运行记录。"""

    run_id: str
    session_id: str | None = None
    mode: str = "single"
    status: str = "queued"
    input: dict[str, Any] = Field(default_factory=dict)
    output: str | None = None
    error: str | None = None
    token_usage: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None


class RunListResponse(BaseModel):
    """GET /api/v1/runs 列表响应（分页）。"""

    items: list[RunResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    size: int = 20


__all__ = ["RunResponse", "RunListResponse"]
