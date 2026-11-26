"""AgentRun 实体 — 每次 Agent / Plan 运行的持久化记录。"""

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


class AgentRun(SQLModel, table=True):  # noqa: F811
    """运行记录表（状态机见 SQL 脚本头注释）。"""

    __tablename__ = "agent_runs"

    run_id: str = Field(primary_key=True, max_length=64)
    session_id: str | None = Field(default=None, index=True, max_length=64)
    tenant_id: str = Field(index=True, max_length=36)
    user_id: str = Field(default="", max_length=36)
    mode: str = Field(default="single", max_length=16)
    status: str = Field(default="queued", max_length=16)
    input: str = Field(default="{}", sa_column=Column("input", Text))
    output: str | None = Field(default=None, sa_column=Column("output", Text))
    error: str | None = Field(default=None, sa_column=Column("error", Text))
    token_usage: str = Field(default="{}", sa_column=Column("token_usage", Text))
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
