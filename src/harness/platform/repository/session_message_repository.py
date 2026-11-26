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

    async def get_in_session(
        self, tenant_id: str, session_id: str, message_id: str
    ):
        """按消息 id + 会话 + 租户查询（未软删）。"""
        from sqlmodel import select
        Record = self.model
        result = await self.session.exec(
            select(Record).where(
                Record.id == message_id,
                Record.session_id == session_id,
                Record.tenant_id == tenant_id,
                Record.deleted_at.is_(None),  # type: ignore[union-attr]
            )
        )
        return result.first()

    async def has_after(self, tenant_id: str, session_id: str, after_seq: int) -> bool:
        """会话内是否存在 seq 更大的未删消息。"""
        from sqlalchemy import func, select
        Record = self.model
        result = await self.session.exec(
            select(func.count()).select_from(Record).where(
                Record.tenant_id == tenant_id,
                Record.session_id == session_id,
                Record.seq > after_seq,
                Record.deleted_at.is_(None),  # type: ignore[union-attr]
            )
        )
        rows = result.all()
        if not rows:
            return False
        value = rows[0]
        count = int(value) if isinstance(value, (int, float)) else int(value[0])
        return count > 0

    async def previous_user(self, tenant_id: str, session_id: str, before_seq: int):
        """按 seq 倒序取目标之前最近的一条未删 user 消息。"""
        from sqlmodel import select
        Record = self.model
        result = await self.session.exec(
            select(Record).where(
                Record.tenant_id == tenant_id,
                Record.session_id == session_id,
                Record.role == "user",
                Record.seq < before_seq,
                Record.deleted_at.is_(None),  # type: ignore[union-attr]
            ).order_by(Record.seq.desc()).limit(1)
        )
        return result.first()

    async def list_up_to(
        self, tenant_id: str, session_id: str, max_seq: int, *, limit: int = 500
    ):
        """按 seq 升序取 ``seq <= max_seq`` 的未删消息（分支复制用）。"""
        from sqlmodel import select
        Record = self.model
        result = await self.session.exec(
            select(Record).where(
                Record.tenant_id == tenant_id,
                Record.session_id == session_id,
                Record.seq <= max_seq,
                Record.deleted_at.is_(None),  # type: ignore[union-attr]
            ).order_by(Record.seq).limit(limit)
        )
        return list(result.all())

    async def list_streaming(self, tenant_id: str, session_id: str):
        """会话内仍处于 streaming 的消息（取消兜底收尾用）。"""
        from sqlmodel import select
        Record = self.model
        result = await self.session.exec(
            select(Record).where(
                Record.tenant_id == tenant_id,
                Record.session_id == session_id,
                Record.status == "streaming",
                Record.deleted_at.is_(None),  # type: ignore[union-attr]
            )
        )
        return list(result.all())
