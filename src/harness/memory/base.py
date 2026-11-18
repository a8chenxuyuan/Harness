"""Memory 系统基类与数据模型。

Memory 是一个轻量持久化层：不引入向量库、不做 RAG 全家桶，
roadmap 明确要求先用简单关键词匹配。
"""

from __future__ import annotations

import abc
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MemoryItem:
    """一条持久化的记忆。

    Attributes:
        item_id: UUID 主键。
        text: 记忆正文。
        metadata: 任意扩展字段（标签、来源、分类等）。
        created_at: 创建时的 time.time() 时间戳。
        session_id: 来源会话 ID，空串表示全局。
    """

    item_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    session_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "text": self.text,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "session_id": self.session_id,
        }


class Memory(abc.ABC):
    """Memory 抽象基类。

    所有实现必须提供 search / save / delete 三个方法；初始化不要求
    持久化路径，由子类决定（内存 dict / SQLite / 远程 API 等）。
    """

    @abc.abstractmethod
    async def search(self, query: str, limit: int = 5) -> list[MemoryItem]:
        """搜索匹配 query 的记忆。

        Args:
            query: 用户输入的关键词或自然语言查询。
            limit: 返回条数上限。

        Returns:
            命中的 MemoryItem 列表，按相关性或时间倒序。
        """

    @abc.abstractmethod
    async def save(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
        session_id: str = "",
    ) -> str:
        """保存一条记忆。

        Args:
            text: 记忆正文。
            metadata: 任意扩展字段。
            session_id: 归属会话 ID。

        Returns:
            新创建的 item_id。
        """

    @abc.abstractmethod
    async def delete(self, item_id: str) -> bool:
        """删除一条记忆。

        Args:
            item_id: 要删除的主键。

        Returns:
            True 表示成功删除；False 表示 item_id 不存在或其他失败。
        """


# --- 工具函数 --------------------------------------------------------------

def new_item_id() -> str:
    """生成一个新的 item_id（UUID v4）。"""
    return str(uuid.uuid4())
