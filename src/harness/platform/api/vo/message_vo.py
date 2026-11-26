"""消息域出参（VO）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class MessageResponse(BaseModel):
    """单条消息。"""

    id: str
    session_id: str
    role: str
    parts: list[dict[str, Any]] = Field(default_factory=list)
    text: str = ""
    seq: int = 0
    parent_id: str | None = None
    status: str = "completed"
    created_at: datetime | None = None


class MessageListResponse(BaseModel):
    """GET /api/v1/sessions/{id}/messages 响应体（seq 游标分页）。"""

    items: list[MessageResponse] = Field(default_factory=list)
    next_cursor: int = 0
    has_more: bool = False


__all__ = ["MessageResponse", "MessageListResponse"]
