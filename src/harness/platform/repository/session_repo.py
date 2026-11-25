"""SessionRepository — 会话元数据表的数据访问。⚠️ SQLModel 延迟加载。"""

from __future__ import annotations

from .base import BaseRepository


class SessionRepository(BaseRepository):
    """会话表 CRUD。"""

    model = None  # type: ignore

    def __init__(self, session) -> None:
        from harness.platform.models.session import SessionRecord
        self.model = SessionRecord
        super().__init__(session)

    async def list_by_user(
        self, tenant_id: str, user_id: str, *, offset: int = 0, limit: int = 20
    ):
        """按租户 + 用户分页列出会话（创建时间倒序）。"""
        from sqlmodel import select
        Record = self.model
        result = await self.session.exec(
            select(Record).where(
                Record.tenant_id == tenant_id,
                Record.user_id == user_id,
            ).order_by(Record.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.all())

    async def count_by_user(self, tenant_id: str, user_id: str) -> int:
        """租户 + 用户维度下的会话总数。"""
        from sqlalchemy import func, select
        Record = self.model
        result = await self.session.exec(
            select(func.count()).select_from(Record).where(
                Record.tenant_id == tenant_id,
                Record.user_id == user_id,
            )
        )
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
