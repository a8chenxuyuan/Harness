"""平台数据仓储 — 归户数据读写与增量游标（W4.1-CHAN-06）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlmodel import func, select

from harness.platform.entity.platform_item import ChannelFetchState, PlatformItem


class PlatformItemRepository:
    """platform_items / channel_fetch_state 的读写封装。"""

    def __init__(self, session: Any) -> None:
        self.session = session

    # --- 数据 -----------------------------------------------------------------

    async def upsert(self, item: PlatformItem) -> bool:
        """按 (binding_id, external_id) 幂等写入；新增返回 True。"""
        existing = (
            await self.session.exec(
                select(PlatformItem)
                .where(PlatformItem.binding_id == item.binding_id)
                .where(PlatformItem.external_id == item.external_id)
            )
        ).first()
        if existing is not None:
            return False
        self.session.add(item)
        await self.session.commit()
        return True

    async def list_today(self, user_id: str, since: datetime) -> list[PlatformItem]:
        """列某用户 since 起的数据（occurred_at 倒序）。"""
        result = await self.session.exec(
            select(PlatformItem)
            .where(PlatformItem.user_id == user_id)
            .where(PlatformItem.occurred_at >= since)
            .order_by(PlatformItem.occurred_at.desc())
        )
        return list(result.all())

    async def count_by_source(self, user_id: str, since: datetime) -> dict[str, int]:
        """按 source 聚合某用户 since 起的数据量。"""
        result = await self.session.exec(
            select(PlatformItem.source, func.count())
            .where(PlatformItem.user_id == user_id)
            .where(PlatformItem.occurred_at >= since)
            .group_by(PlatformItem.source)
        )
        return {row[0]: row[1] for row in result.all()}

    # --- 游标 -----------------------------------------------------------------

    async def get_state(self, binding_id: str, source: str) -> ChannelFetchState | None:
        result = await self.session.exec(
            select(ChannelFetchState)
            .where(ChannelFetchState.binding_id == binding_id)
            .where(ChannelFetchState.source == source)
        )
        return result.first()

    async def set_state(
        self,
        binding_id: str,
        source: str,
        *,
        cursor: str = "",
        error: str = "",
    ) -> None:
        """更新游标 / 同步时间 / 错误（无则建）。"""
        state = await self.get_state(binding_id, source)
        if state is None:
            state = ChannelFetchState(
                id=str(uuid.uuid4()), binding_id=binding_id, source=source
            )
        state.cursor = cursor or state.cursor
        state.last_error = error
        state.last_synced_at = datetime.now(timezone.utc) if not error else state.last_synced_at
        self.session.add(state)
        await self.session.commit()


__all__ = ["PlatformItemRepository"]
