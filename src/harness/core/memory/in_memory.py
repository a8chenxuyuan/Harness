"""InMemoryMemory：基于 Python dict 的内存实现。

适合单元测试、单会话快速跑通；进程重启即丢失。
search 做简单的关键词包含匹配（大小写不敏感）。
"""

from __future__ import annotations

import logging
from typing import Any

from .base import Memory, MemoryItem, new_item_id

log = logging.getLogger(__name__)


class InMemoryMemory(Memory):
    """内存版 Memory。

    Attributes:
        _items: item_id → MemoryItem 映射。
    """

    def __init__(self) -> None:
        self._items: dict[str, MemoryItem] = {}

    # --- Memory 接口 -----------------------------------------------------------

    async def search(self, query: str, limit: int = 5) -> list[MemoryItem]:
        if not query:
            return []
        needle = query.lower()
        matches = [
            item
            for item in self._items.values()
            if needle in item.text.lower()
        ]
        # 按时间倒序，取前 limit
        matches.sort(key=lambda it: -it.created_at)
        return matches[:limit]

    async def save(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
        session_id: str = "",
    ) -> str:
        item = MemoryItem(
            item_id=new_item_id(),
            text=text,
            metadata=dict(metadata or {}),
            session_id=session_id,
        )
        self._items[item.item_id] = item
        return item.item_id

    async def delete(self, item_id: str) -> bool:
        if item_id in self._items:
            del self._items[item_id]
            return True
        return False

    # --- 便捷 -----------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._items)

    def all_items(self) -> list[MemoryItem]:
        return list(self._items.values())
