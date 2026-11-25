"""Tenant 实体 — 多租户隔离的顶层容器。

⚠️ SQLModel 可能因 Windows 策略阻止 C 扩展而不可用。
这里用 try/except 兜底保证模块 import 不炸，真正用的时候才报错。
"""

from __future__ import annotations

from datetime import datetime, timezone

try:
    from sqlmodel import Field, SQLModel  # type: ignore
    _SQLMODEL_AVAILABLE = True
except Exception:  # noqa: BLE001
    _SQLMODEL_AVAILABLE = False

    # 最小 stub，保证 class Tenant(SQLModel, table=True) 至少能定义出来
    class Field:  # type: ignore[no-redef]
        def __init__(self, *a, **kw): ...
    class SQLModel:  # type: ignore[no-redef]
        def __init_subclass__(cls, **kw): ...


class Tenant(SQLModel, table=True):  # noqa: F811 — SQLModel 由 try 块定义
    """租户表（多租户隔离顶层容器）。"""

    __tablename__ = "tenants"

    id: str = Field(primary_key=True, max_length=36)
    name: str = Field(max_length=128, description="租户显示名")
    plan: str = Field(default="free", max_length=32, description="free | pro | enterprise")
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
