"""MemoryRepository — memories 表的数据访问（Phase 24）。

与 core/memory/long_term.py 的 SQLite 版保持同样的匹配语义（LIKE 关键词），
但走 SQLModel AsyncSession，天然支持 SQLite / PostgreSQL 双后端。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from harness.platform.models.memory import MemoryEntry


def _like_pattern(query: str) -> str:
    """转义 LIKE 通配符，防止用户输入改变查询语义。"""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class MemoryRepository:
    """长期记忆表 CRUD（租户隔离）。"""

    def __init__(self, session) -> None:
        self.session = session

    async def save(
        self,
        *,
        tenant_id: str,
        user_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> str:
        """写入一条记忆，返回 item_id。"""
        item_id = str(uuid.uuid4())
        self.session.add(
            MemoryEntry(
                id=item_id,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                content=content,
                metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
            )
        )
        await self.session.commit()
        return item_id

    async def search(
        self,
        tenant_id: str,
        query: str,
        *,
        user_id: str | None = None,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        """按关键词模糊匹配（大小写不敏感），时间倒序。"""
        if not query:
            return []
        from sqlmodel import select

        stmt = select(MemoryEntry).where(
            MemoryEntry.tenant_id == tenant_id,
            MemoryEntry.content.ilike(  # type: ignore[attr-defined]
                _like_pattern(query), escape="\\"
            ),
        )
        if user_id:
            stmt = stmt.where(MemoryEntry.user_id == user_id)
        stmt = stmt.order_by(MemoryEntry.created_at.desc()).limit(limit)  # type: ignore[attr-defined]
        result = await self.session.exec(stmt)
        return list(result.all())

    async def list_by_tenant(
        self, tenant_id: str, *, offset: int = 0, limit: int = 20
    ) -> list[MemoryEntry]:
        """分页列出租户记忆。"""
        from sqlmodel import select

        result = await self.session.exec(
            select(MemoryEntry)
            .where(MemoryEntry.tenant_id == tenant_id)
            .order_by(MemoryEntry.created_at.desc())  # type: ignore[attr-defined]
            .offset(offset)
            .limit(limit)
        )
        return list(result.all())

    async def delete(self, tenant_id: str, item_id: str) -> bool:
        """按 id + 租户删除，返回是否真的删掉了。"""
        from sqlalchemy import delete

        result = await self.session.exec(
            delete(MemoryEntry).where(
                MemoryEntry.id == item_id,
                MemoryEntry.tenant_id == tenant_id,
            )
        )
        await self.session.commit()
        return bool(getattr(result, "rowcount", 0))


__all__ = ["MemoryRepository"]
