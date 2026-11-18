"""Memory 系统（Phase 14）。

对外导出：
    * Memory / MemoryItem — 基类与数据模型
    * InMemoryMemory — 内存实现
    * LongTermMemory — SQLite 持久化实现
    * SessionMemoryView — 从 AgentState 抽取记忆的适配器
    * memory_search / memory_save — 便捷工具函数（基于 LongTermMemory）
    * create_memory_tools — 工厂：把任意 Memory 包成两个 BaseTool
"""

from .base import Memory, MemoryItem
from .in_memory import InMemoryMemory
from .long_term import LongTermMemory
from .session_view import SessionMemoryView
from .tools import create_memory_tools


def memory_search(
    memory: Memory,
    query: str,
    limit: int = 5,
) -> list[MemoryItem]:
    """便捷同步包装：await memory.search(...)。

    注意：这是一个普通函数，不异步执行。在异步上下文里请直接 await memory.search(...)。
    """
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        return asyncio.run(memory.search(query=query, limit=limit))
    # 已有 running loop：无法从同步函数里发起异步，抛错提示用户
    raise RuntimeError(
        "memory_search 是便捷同步包装，不能在已有事件循环里调用。请直接 await memory.search(...)。"
    )


def memory_save(
    memory: Memory,
    text: str,
    metadata: dict | None = None,
    session_id: str = "",
) -> str:
    """便捷同步包装：await memory.save(...)。"""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        return asyncio.run(memory.save(text=text, metadata=metadata, session_id=session_id))
    raise RuntimeError(
        "memory_save 是便捷同步包装，不能在已有事件循环里调用。请直接 await memory.save(...)。"
    )


__all__ = [
    "Memory",
    "MemoryItem",
    "InMemoryMemory",
    "LongTermMemory",
    "SessionMemoryView",
    "create_memory_tools",
    "memory_search",
    "memory_save",
]
