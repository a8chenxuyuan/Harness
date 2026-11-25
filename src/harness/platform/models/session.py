"""SessionRecord 实体 — 持久化的 Agent 会话元数据。"""

from __future__ import annotations

from datetime import datetime, timezone

try:
    from sqlmodel import Field, SQLModel  # type: ignore
    from sqlalchemy import Column, Text  # type: ignore
except Exception:  # noqa: BLE001
    class Field:  # type: ignore[no-redef]
        def __init__(self, *a, **kw): ...
    class SQLModel:  # type: ignore[no-redef]
        def __init_subclass__(cls, **kw): ...


class SessionRecord(SQLModel, table=True):  # noqa: F811
    """会话表。"""

    __tablename__ = "sessions"

    session_id: str = Field(primary_key=True, max_length=64)
    tenant_id: str = Field(index=True, max_length=36)
    user_id: str = Field(index=True, max_length=36)
    title: str = Field(default="", max_length=256)
    status: str = Field(default="active", max_length=16)
    message_count: int = Field(default=0)
    metadata_json: str = Field(default="{}", sa_column=Column("metadata", Text))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
