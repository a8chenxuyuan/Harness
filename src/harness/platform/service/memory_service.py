"""Memory 管理服务 —— 封装 core 层 LongTermMemory 对外暴露 HTTP 能力。

职责：
    1. 单例管理 LongTermMemory（SQLite 持久化）
    2. 把 core 层 MemoryItem dataclass 转成 API VO（MemoryItemVO）
    3. 提供关键词搜索 + 分页列表
    4. 手动保存/删除记忆

设计决策：
    - LongTermMemory 抽象基类只有 search/save/delete，没有 list_all / count / 分页
      所以 Service 层用独立的 sqlite3 连接做 list 查询，不干扰 LongTermMemory 自己的连接
    - db_path 从 Settings 读，默认 ``{cwd}/.harness/memories.db``
    - Memory 跨租户：目前是全局共享的（没有 tenant_id 字段），后续加租户隔离时改表结构
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from harness.core.memory.base import MemoryItem
from harness.core.memory.long_term import LongTermMemory

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 单例管理
# ---------------------------------------------------------------------------

_memory_instance: LongTermMemory | None = None
_db_path_cache: Path | None = None


def _resolve_db_path() -> Path:
    """解析 SQLite 文件路径。

    优先级：env ``HARNESS_MEMORY_DB`` > Settings（如有）> 默认 ``{cwd}/.harness/memories.db``。
    """
    env_val = os.environ.get("HARNESS_MEMORY_DB")
    if env_val:
        return Path(env_val)
    # 尝试从 Settings 读
    try:
        from harness.common.config.settings import Settings

        s = Settings()
        raw = getattr(s, "memory_db_path", "") or getattr(s, "MEMORY_DB_PATH", "")
        if raw:
            return Path(raw)
    except Exception:  # noqa: BLE001
        pass
    # 默认：项目根目录 .harness/memories.db
    return Path(os.getcwd()) / ".harness" / "memories.db"


def get_memory() -> LongTermMemory:
    """返回进程内单例 LongTermMemory。首次调用会懒加载。"""
    global _memory_instance, _db_path_cache
    if _memory_instance is None:
        _db_path_cache = _resolve_db_path()
        _memory_instance = LongTermMemory(str(_db_path_cache))
        log.info("MemoryService: LongTermMemory 单例已创建，db=%s", _db_path_cache)
    return _memory_instance


# ---------------------------------------------------------------------------
# 核心业务方法
# ---------------------------------------------------------------------------

async def list_memories(
    keyword: str = "",
    *,
    limit: int = 50,
    offset: int = 0,
    session_id: str | None = None,
) -> tuple[list[MemoryItem], int]:
    """分页查询记忆。

    Args:
        keyword: 关键词（LIKE 匹配）；空字符串返回全部
        limit: 返回条数上限
        offset: 分页偏移
        session_id: 限定来源会话；None 表示不筛选

    Returns:
        (items, total) — items 是当前页数据，total 是不受 limit/offset 限制的总数
    """
    db_path = _resolve_db_path()

    def _do_query() -> tuple[list[MemoryItem], int]:
        """同步 SQL 查询（跑在 to_thread 里不阻塞事件循环）。"""
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA case_sensitive_like = OFF;")

        # --- 动态拼 WHERE ---
        where_parts: list[str] = []
        params: list[Any] = []

        if keyword:
            like_needle = "%" + keyword.replace("%", "%%").replace("_", "\\_") + "%"
            where_parts.append("text LIKE ? ESCAPE '\\'")
            params.append(like_needle)

        if session_id is not None:
            # session_id 为空串的也属于全局，筛选时要考虑
            where_parts.append("session_id = ?")
            params.append(session_id)

        where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        # --- COUNT 总条数 ---
        count_sql = f"SELECT COUNT(*) FROM memories {where_clause}"
        total_row = conn.execute(count_sql, params).fetchone()
        total = int(total_row[0]) if total_row else 0

        # --- 分页查询 ---
        select_sql = (
            f"SELECT item_id, session_id, text, metadata, created_at "
            f"FROM memories {where_clause} "
            f"ORDER BY created_at DESC "
            f"LIMIT ? OFFSET ?"
        )
        rows = conn.execute(select_sql, [*params, limit, offset]).fetchall()

        items: list[MemoryItem] = []
        for row in rows:
            try:
                meta = json.loads(row["metadata"]) if row["metadata"] else {}
            except json.JSONDecodeError:
                meta = {}
            items.append(
                MemoryItem(
                    item_id=row["item_id"],
                    session_id=row["session_id"],
                    text=row["text"],
                    metadata=meta,
                    created_at=row["created_at"],
                )
            )
        conn.close()
        return items, total

    return await asyncio.to_thread(_do_query)


async def save_memory(
    *,
    content: str,
    session_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, float]:
    """手动保存一条长期记忆。

    Args:
        content: 记忆正文
        session_id: 来源会话；None 表示全局（存空串）
        tags: 标签列表，写入 metadata.tags
        metadata: 扩展字段（会被 tags 覆盖同名 key）

    Returns:
        (item_id, created_at_ts) — item_id 是 UUID 字符串，created_at 是秒级时间戳
    """
    mem = get_memory()
    meta = dict(metadata or {})
    if tags:
        meta["tags"] = list(tags)
    sid = session_id or ""

    item_id = await mem.save(text=content, metadata=meta, session_id=sid)

    # 回读 created_at（save 方法不返回时间戳）
    # SQLite 的 memories 表 created_at 是 REAL（秒），直接跑一条 SQL 查
    db_path = _resolve_db_path()

    def _get_ts() -> float:
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT created_at FROM memories WHERE item_id = ?", (item_id,)
            ).fetchone()
            return float(row[0]) if row else 0.0
        finally:
            conn.close()

    ts = await asyncio.to_thread(_get_ts)
    log.info("MemoryService.save_memory: 已保存 %s (session=%s)", item_id, sid)
    return item_id, ts


async def delete_memory(item_id: str) -> bool:
    """按 item_id 删除记忆。

    Args:
        item_id: UUID 主键

    Returns:
        True=确实删除了；False=item_id 不存在
    """
    mem = get_memory()
    ok = await mem.delete(item_id)
    if ok:
        log.info("MemoryService.delete_memory: 已删除 %s", item_id)
    return ok


async def search_memory(query: str, limit: int = 5) -> list[MemoryItem]:
    """关键词搜索（供 Agent 运行时调用，不走 HTTP）。"""
    mem = get_memory()
    return await mem.search(query, limit=limit)


async def count_memories() -> int:
    """返回当前记忆总数。"""
    mem = get_memory()
    return await mem.count()


__all__ = [
    "get_memory",
    "list_memories",
    "save_memory",
    "delete_memory",
    "search_memory",
    "count_memories",
]
