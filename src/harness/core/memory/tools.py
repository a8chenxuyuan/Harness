"""Memory as Tool：把 Memory 实现包成可供 LLM 调用的工具。

两个工具：
    - memory_search(query, limit) — 查询记忆，返回 JSON
    - memory_save(text, metadata_json) — 保存记忆，返回 item_id

**只读/写标记**：memory_search 是 readonly=True；memory_save 是 readonly=False。
这样工具执行器可以把 search 并行跑、save 串行跑。

**用法**：LLM 拿到 query 后调用 memory_search 得到 JSON 列表，自己挑用哪些；
拿到需要长期记住的内容后调用 memory_save 存起来。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from harness.core.tool.reflective import ReflectiveTool, tool

if TYPE_CHECKING:
    from .base import Memory

log = logging.getLogger(__name__)


def create_memory_tools(memory: "Memory") -> tuple[ReflectiveTool, ReflectiveTool]:
    """基于同一个 Memory 实例生成 (memory_search, memory_save) 两个工具。

    Args:
        memory: 任何 Memory 实现（InMemoryMemory / LongTermMemory / ...）。

    Returns:
        (ReflectiveTool, ReflectiveTool) 元组。
    """
    # 闭包捕获 memory 实例
    async def _do_search(query: str, limit: int = 5) -> str:
        """Search long-term memory by keyword. Use this when the user asks about past conversations,
        previously discussed topics, or any context that might have been stored earlier.
        Returns a JSON array of memory items sorted by recency; empty array means no match."""
        items = await memory.search(query=query, limit=limit)
        payload = [it.to_dict() for it in items]
        return json.dumps(payload, ensure_ascii=False)

    async def _do_save(text: str, metadata_json: str = "{}") -> str:
        """Save an important piece of information to long-term memory. Use this when the user states
        a preference, mentions a persistent fact, or gives an instruction that should persist across
        sessions. Returns the new memory item_id as a string.

        Args:
            text: The content to remember, usually a concise sentence or bullet.
            metadata_json: Optional JSON string of tags (e.g. {"tag":"preference"}).
        """
        meta: dict = {}
        if metadata_json:
            try:
                parsed = json.loads(metadata_json)
                if isinstance(parsed, dict):
                    meta = parsed
            except json.JSONDecodeError:
                log.warning("memory_save: metadata_json 解析失败，忽略：%s", metadata_json)
        item_id = await memory.save(text=text, metadata=meta)
        return json.dumps({"item_id": item_id}, ensure_ascii=False)

    search_tool = tool()(_do_search)
    search_tool.readonly = True

    save_tool = tool(readonly=False)(_do_save)
    return search_tool, save_tool
