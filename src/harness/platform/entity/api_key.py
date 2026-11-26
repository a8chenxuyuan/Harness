"""ApiKey 实体 — 机器调用凭据（W4-API-01）。

不存明文 key，只存 SHA-256 哈希；``key_prefix``（``hk_`` + 8 位）
用于列表展示与人工辨认。API Key 通过 ``Authorization: Bearer hk_...``
携带，与 JWT 共用同一个鉴权入口（deps.get_current_user 按前缀分流）。
"""

from __future__ import annotations

from datetime import datetime, timezone

try:
    from sqlmodel import Field, SQLModel  # type: ignore
except Exception:  # noqa: BLE001
    class Field:  # type: ignore[no-redef]
        def __init__(self, *a, **kw): ...

    class SQLModel:  # type: ignore[no-redef]
        def __init_subclass__(cls, **kw): ...


class ApiKey(SQLModel, table=True):  # noqa: F811
    """API Key 持久化记录。"""

    __tablename__ = "api_keys"

    id: str = Field(primary_key=True, max_length=36)
    name: str = Field(max_length=128)
    key_prefix: str = Field(index=True, max_length=16)
    key_hash: str = Field(unique=True, max_length=64)
    tenant_id: str = Field(index=True, max_length=36)
    created_by: str = Field(max_length=36)
    # 权限范围：预留字段，当前统一 "all"（后续可细分读写/模块级 scope）
    scopes: str = Field(default="all", max_length=128)
    is_active: bool = Field(default=True)
    last_used_at: datetime | None = Field(default=None)
    expires_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
