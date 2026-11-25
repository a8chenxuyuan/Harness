"""AuditLog 实体 — 审计日志（工具调用 + API 访问）。"""

from __future__ import annotations

from datetime import datetime, timezone

try:
    from sqlmodel import Field, SQLModel  # type: ignore
    from sqlalchemy import Column, Integer, Text  # type: ignore
except Exception:  # noqa: BLE001
    class Field:  # type: ignore[no-redef]
        def __init__(self, *a, **kw): ...
    class SQLModel:  # type: ignore[no-redef]
        def __init_subclass__(cls, **kw): ...


class AuditLog(SQLModel, table=True):  # noqa: F811
    """审计日志表。"""

    __tablename__ = "audit_logs"

    id: int | None = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
    tenant_id: str = Field(index=True, max_length=36)
    user_id: str = Field(index=True, max_length=36)
    session_id: str | None = Field(default=None, index=True, max_length=64)
    action: str = Field(index=True, max_length=64)
    target: str = Field(default="", max_length=256)
    result: str = Field(default="success", max_length=16)
    detail_json: str = Field(default="{}", sa_column=Column("detail", Text))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
