"""SessionRepository — 会话元数据表的数据访问。⚠️ SQLModel 延迟加载。"""

from __future__ import annotations

from .repository_base import BaseRepository


class SessionRepository(BaseRepository):
    """会话表 CRUD。"""

    model = None  # type: ignore

    def __init__(self, session) -> None:
        from harness.platform.entity.session import SessionRecord
        self.model = SessionRecord
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
        """按租户 + 用户分页列出会话（创建时间倒序），可按状态过滤。"""
        from sqlmodel import select
        Record = self.model
        stmt = select(Record).where(
            Record.tenant_id == tenant_id,
            Record.user_id == user_id,
        )
        if status:
            stmt = stmt.where(Record.status == status)
        result = await self.session.exec(
            stmt.order_by(Record.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.all())

    async def count_by_user(
        self, tenant_id: str, user_id: str, *, status: str | None = None
    ) -> int:
        """租户 + 用户维度下的会话总数，可按状态过滤。"""
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

    async def get_by_id(self, tenant_id: str, session_id: str):
        """按 id + 租户隔离查询。"""
        from sqlmodel import select
        Record = self.model
        result = await self.session.exec(
            select(Record).where(
                Record.session_id == session_id,
                Record.tenant_id == tenant_id,
            )
        )
        return result.first()

    async def get_by_owner(self, tenant_id: str, user_id: str, session_id: str):
        """按 id + 租户 + 属主查询（同租户用户之间也互不可见）。"""
        from sqlmodel import select
        Record = self.model
        result = await self.session.exec(
            select(Record).where(
                Record.session_id == session_id,
                Record.tenant_id == tenant_id,
                Record.user_id == user_id,
            )
        )
        return result.first()
