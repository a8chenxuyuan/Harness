"""SessionMessage 实体 — 会话消息（append-only，可按 parent_id 分支）。"""

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


class SessionMessage(SQLModel, table=True):  # noqa: F811
    """会话消息表。

    ``parts`` 存 JSON 数组字符串（PG 侧列为 JSONB，SQLite 侧为 TEXT），
    元素结构见 ``sql/2026/11/V20261125_session_messages_create.sql``。
    """

    __tablename__ = "session_messages"

    id: str = Field(primary_key=True, max_length=64)
    session_id: str = Field(index=True, max_length=64)
    tenant_id: str = Field(index=True, max_length=36)
    user_id: str = Field(default="", max_length=36)
    role: str = Field(max_length=16)
    parts: str = Field(default="[]", sa_column=Column("parts", Text))
    text: str = Field(default="", sa_column=Column("text", Text))
    seq: int = Field(default=0)
    parent_id: str | None = Field(default=None, max_length=64)
    status: str = Field(default="completed", max_length=16)
    deleted_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
