"""IdempotencyRecord 实体 — 幂等键（W3-KERN-02）。

同一租户 + 场景 + 幂等键唯一，记录首次请求的入参哈希与响应，
用于「网络重试不重复执行」：同步接口可回放缓存响应，流式接口返回冲突提示。
"""

from __future__ import annotations

from datetime import datetime, timezone

try:
    from sqlmodel import Field, SQLModel  # type: ignore
    from sqlalchemy import Column, Text, UniqueConstraint  # type: ignore
except Exception:  # noqa: BLE001
    class Field:  # type: ignore[no-redef]
        def __init__(self, *a, **kw): ...

    class SQLModel:  # type: ignore[no-redef]
        def __init_subclass__(cls, **kw): ...

    class Column:  # type: ignore[no-redef]
        def __init__(self, *a, **kw): ...

    class Text:  # type: ignore[no-redef]
        pass

    class UniqueConstraint:  # type: ignore[no-redef]
        def __init__(self, *a, **kw): ...


class IdempotencyRecord(SQLModel, table=True):  # noqa: F811
    """幂等键记录表。

    status:
        in_progress — 首次请求处理中（重复请求返回 409）
        succeeded   — 已成功，response_json 可用于同步回放
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "scope", "key", name="uq_idempotency_tenant_scope_key"
        ),
    )

    id: str = Field(primary_key=True, max_length=36)
    tenant_id: str = Field(index=True, max_length=36)
    scope: str = Field(max_length=32)
    key: str = Field(max_length=128)
    request_hash: str = Field(max_length=64)
    status: str = Field(default="in_progress", max_length=16)
    run_id: str | None = Field(default=None, max_length=64)
    response_json: str | None = Field(
        default=None, sa_column=Column("response_json", Text)
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
