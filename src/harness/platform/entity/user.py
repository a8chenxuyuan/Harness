"""User 实体 — 租户下的用户账号。"""

from __future__ import annotations

from datetime import datetime, timezone

try:
    from sqlmodel import Field, SQLModel  # type: ignore
except Exception:  # noqa: BLE001
    class Field:  # type: ignore[no-redef]
        def __init__(self, *a, **kw): ...
    class SQLModel:  # type: ignore[no-redef]
        def __init_subclass__(cls, **kw): ...


class User(SQLModel, table=True):  # noqa: F811
    """用户表。"""

    __tablename__ = "users"

    id: str = Field(primary_key=True, max_length=36)
    tenant_id: str = Field(index=True, max_length=36)
    username: str = Field(index=True, max_length=64)
    email: str = Field(max_length=256, default="")
    hashed_password: str = Field(max_length=256)
    role: str = Field(default="member", max_length=16)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
