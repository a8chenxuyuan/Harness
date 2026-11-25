"""PlanRecord 实体 — 已生成计划的持久化元数据（Phase 23/24）。

只存「计划本身」：goal、步骤 JSON、原文哈希、审批状态。
运行态（后台 task / 取消信号）不落库，由 service.run_registry 在进程内维护。
"""

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


class PlanRecord(SQLModel, table=True):  # noqa: F811
    """计划表。"""

    __tablename__ = "plans"

    plan_id: str = Field(primary_key=True, max_length=64)
    tenant_id: str = Field(index=True, max_length=36)
    user_id: str = Field(index=True, max_length=36)
    goal: str = Field(default="", sa_column=Column("goal", Text))
    steps_json: str = Field(default="[]", sa_column=Column("steps", Text))
    plan_text: str = Field(default="", sa_column=Column("plan_text", Text))
    plan_hash: str = Field(default="", max_length=80)
    approved: bool = Field(default=False)
    status: str = Field(default="pending", max_length=16)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
