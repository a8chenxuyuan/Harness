"""RefreshToken 实体 — refresh token 轮换与吊销（W3-SEC-01）。

不存明文 token，只存 SHA-256 哈希；主键复用 JWT 的 ``jti``。
轮换后旧记录 ``revoked_at`` 非空并记录 ``replaced_by``，
再次使用旧 token 即判定为重放，吊销该用户全部 refresh token。
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


class RefreshToken(SQLModel, table=True):  # noqa: F811
    """refresh token 持久化记录。"""

    __tablename__ = "refresh_tokens"

    jti: str = Field(primary_key=True, max_length=64)
    user_id: str = Field(index=True, max_length=36)
    tenant_id: str = Field(max_length=36)
    token_hash: str = Field(max_length=64)
    expires_at: datetime
    revoked_at: datetime | None = Field(default=None)
    replaced_by: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
