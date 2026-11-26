"""审计查询 VO — 列表项与分页响应。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AuditLogItem(BaseModel):
    """单条审计日志（detail 已解析为对象，时间统一 ISO-8601 UTC）。"""

    id: int
    user_id: str
    session_id: str | None = None
    action: str
    target: str = ""
    result: str = "success"
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class AuditLogListResponse(BaseModel):
    """GET /api/v1/audit-logs 响应体。"""

    items: list[AuditLogItem] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    size: int = 20


__all__ = ["AuditLogItem", "AuditLogListResponse"]
