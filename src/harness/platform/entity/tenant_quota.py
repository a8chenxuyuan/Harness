"""租户配额实体（W3-PLAT-01）。"""

from __future__ import annotations

from datetime import datetime, timezone

try:
    from sqlmodel import Field, SQLModel  # type: ignore
except Exception:  # noqa: BLE001
    class Field:  # type: ignore[no-redef]
        def __init__(self, *a, **kw): ...

    class SQLModel:  # type: ignore[no-redef]
        def __init_subclass__(cls, **kw): ...


class TenantQuota(SQLModel, table=True):  # noqa: F811
    """租户配额表（租户主键，缺省值即免费版额度）。"""

    __tablename__ = "tenant_quotas"

    tenant_id: str = Field(primary_key=True, max_length=36)
    max_concurrent_runs: int = Field(default=4)
    max_daily_messages: int = Field(default=2000)
    max_daily_tokens: int = Field(default=2_000_000)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TenantUsageDaily(SQLModel, table=True):  # noqa: F811
    """租户按天用量表（tenant_id + usage_date 复合主键）。"""

    __tablename__ = "tenant_usage_daily"

    tenant_id: str = Field(primary_key=True, max_length=36)
    usage_date: str = Field(primary_key=True, max_length=10)
    runs_started: int = Field(default=0)
    messages: int = Field(default=0)
    tokens: int = Field(default=0)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
