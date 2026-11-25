"""MemoryEntry 实体 — 长期记忆条目。"""

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


class MemoryEntry(SQLModel, table=True):  # noqa: F811
    """长期记忆表。"""

    __tablename__ = "memories"

    id: str = Field(primary_key=True, max_length=36)
    tenant_id: str = Field(index=True, max_length=36)
    user_id: str = Field(index=True, max_length=36)
    session_id: str | None = Field(default=None, index=True, max_length=64)
    content: str = Field(default="")
    metadata_json: str = Field(default="{}", sa_column=Column("metadata", Text))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
