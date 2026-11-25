"""AgentRunRepository — 运行记录表的数据访问。⚠️ SQLModel 延迟加载。"""

from __future__ import annotations

from .repository_base import BaseRepository


class AgentRunRepository(BaseRepository):
    """运行记录的写入与按用户查询。"""

    model = None  # type: ignore

    def __init__(self, session) -> None:
        from harness.platform.entity.agent_run import AgentRun
        self.model = AgentRun
        super().__init__(session)

    async def list_by_user(
        self,
        tenant_id: str,
        user_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
        status: str | None = None,
    ):
        """按租户 + 用户分页列出运行记录（创建时间倒序）。"""
        from sqlmodel import select
        Record = self.model
        stmt = select(Record).where(
            Record.tenant_id == tenant_id,
            Record.user_id == user_id,
        )
        if status:
            stmt = stmt.where(Record.status == status)
        result = await self.session.exec(
            stmt.order_by(Record.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.all())

    async def count_by_user(
        self, tenant_id: str, user_id: str, *, status: str | None = None
    ) -> int:
        """按租户 + 用户统计运行记录数。"""
        from sqlalchemy import func, select
        Record = self.model
        stmt = select(func.count()).select_from(Record).where(
            Record.tenant_id == tenant_id,
            Record.user_id == user_id,
        )
        if status:
            stmt = stmt.where(Record.status == status)
        result = await self.session.exec(stmt)
        rows = result.all()
        if not rows:
            return 0
        value = rows[0]
        return int(value) if isinstance(value, (int, float)) else int(value[0])

    async def get_by_owner(self, tenant_id: str, user_id: str, run_id: str):
        """按 run_id + 租户 + 发起人查询。"""
        from sqlmodel import select
        Record = self.model
        result = await self.session.exec(
            select(Record).where(
                Record.run_id == run_id,
                Record.tenant_id == tenant_id,
                Record.user_id == user_id,
            )
        )
        return result.first()
