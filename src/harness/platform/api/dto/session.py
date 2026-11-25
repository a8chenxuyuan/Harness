"""Session 相关 DTO。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    """POST /api/v1/sessions 请求体。"""

    title: str = Field(default="", max_length=256)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionResponse(BaseModel):
    """GET /api/v1/sessions/{id} 响应体。"""

    session_id: str
    title: str = ""
    status: str = "active"
    message_count: int = 0


class SessionListResponse(BaseModel):
    """GET /api/v1/sessions 列表响应（分页）。"""

    items: list[SessionResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    size: int = 20


__all__ = ["SessionCreateRequest", "SessionResponse", "SessionListResponse"]
