"""SessionMessageRepository — 会话消息表的数据访问。⚠️ SQLModel 延迟加载。"""

from __future__ import annotations

from .repository_base import BaseRepository


class SessionMessageRepository(BaseRepository):
    """会话消息的追加与按序查询。"""

    model = None  # type: ignore

    def __init__(self, session) -> None:
        from harness.platform.entity.session_message import SessionMessage
        self.model = SessionMessage
        super().__init__(session)

    async def list_by_session(
        self,
        tenant_id: str,
        session_id: str,
        *,
        after_seq: int = 0,
        limit: int = 50,
    ):
        """按会话 + 租户查询消息，seq 游标分页（升序，未软删）。"""
        from sqlmodel import select
        Record = self.model
        result = await self.session.exec(
            select(Record).where(
                Record.tenant_id == tenant_id,
                Record.session_id == session_id,
                Record.seq > after_seq,
                Record.deleted_at.is_(None),  # type: ignore[union-attr]
            ).order_by(Record.seq).limit(limit)
        )
        return list(result.all())

    async def next_seq(self, tenant_id: str, session_id: str) -> int:
        """会话内下一个序号（max(seq) + 1，空会话从 1 开始）。"""
        from sqlalchemy import func, select
        Record = self.model
        result = await self.session.exec(
            select(func.max(Record.seq)).where(
                Record.tenant_id == tenant_id,
                Record.session_id == session_id,
            )
        )
        value = result.first()
        # SQLModel 的 exec 在不同版本下可能返回标量或单列 Row，统一取值
        if value is None:
            return 1
        if not isinstance(value, (int, float)):
            try:
                value = value[0]  # type: ignore[index]
            except (TypeError, IndexError, KeyError):
                return 1
        return int(value) + 1 if isinstance(value, (int, float)) else 1

    async def count_by_session(self, tenant_id: str, session_id: str) -> int:
        """会话内未删除的消息条数。"""
        from sqlalchemy import func, select
        Record = self.model
        result = await self.session.exec(
            select(func.count()).select_from(Record).where(
                Record.tenant_id == tenant_id,
                Record.session_id == session_id,
                Record.deleted_at.is_(None),  # type: ignore[union-attr]
            )
        )
        rows = result.all()
        if not rows:
            return 0
        value = rows[0]
        return int(value) if isinstance(value, (int, float)) else int(value[0])
