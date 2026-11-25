"""Session 域出参（VO）。

请求模型在 ``api.dto.session``。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SessionResponse(BaseModel):
    """GET /api/v1/sessions/{id} 响应体。"""

    session_id: str
    title: str = ""
    status: str = "active"
    message_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SessionListResponse(BaseModel):
    """GET /api/v1/sessions 列表响应（分页）。"""

    items: list[SessionResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    size: int = 20


__all__ = ["SessionResponse", "SessionListResponse"]
