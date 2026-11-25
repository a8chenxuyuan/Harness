"""LongTermMemory：基于 SQLite 的持久化记忆存储。

roadmap 明确不做 RAG 全家桶，用最简单的 LIKE 关键词匹配。
SQLite 零依赖、单文件、并发友好，适合作为长期记忆底座。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from .base import Memory, MemoryItem, new_item_id

log = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    item_id    TEXT PRIMARY KEY,
    session_id TEXT NOT NULL DEFAULT '',
    text       TEXT NOT NULL,
    metadata   TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id);
CREATE INDEX IF NOT EXISTS idx_memories_created  ON memories(created_at);
"""


class LongTermMemory(Memory):
    """SQLite 持久化 Memory 实现。

    用 run_in_executor 包装 sqlite3 同步调用，避免阻塞事件循环。

    Attributes:
        _db_path: 数据库文件路径。
        _conn: sqlite3 连接对象，在首次操作时懒初始化。
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()  # 保护首次打开和 schema 初始化

    # --- 打开 / 关闭 -----------------------------------------------------------

    async def _ensure_open(self) -> sqlite3.Connection:
        """懒初始化数据库连接，幂等。"""
        if self._conn is not None:
            return self._conn

        async with self._lock:
            if self._conn is not None:
                return self._conn

            # 确保父目录存在
            self._db_path.parent.mkdir(parents=True, exist_ok=True)

            # check_same_thread=False 允许跨线程使用（我们用 run_in_executor）
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            # 让 LIKE 支持大小写不敏感（sqlite3 默认即可，但显式声明更安全）
            conn.execute("PRAGMA case_sensitive_like = OFF;")

            # 建表
            await asyncio.to_thread(conn.executescript, _SCHEMA_SQL)

            self._conn = conn
            log.info("LongTermMemory: SQLite 已打开 %s", self._db_path)
            return conn

    async def close(self) -> None:
        """关闭数据库连接。幂等。"""
        async with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # --- Memory 接口 -----------------------------------------------------------

    async def search(self, query: str, limit: int = 5) -> list[MemoryItem]:
        if not query:
            return []
        conn = await self._ensure_open()

        # 转义 LIKE 通配符，避免用户输入破坏 SQL
        like_needle = "%" + query.replace("%", "%%").replace("_", "\\_") + "%"

        sql = """
            SELECT item_id, session_id, text, metadata, created_at
            FROM memories
            WHERE text LIKE ? ESCAPE '\\'
            ORDER BY created_at DESC
            LIMIT ?
        """
        rows = await asyncio.to_thread(
            conn.execute, sql, (like_needle, limit)
        )
        rows = await asyncio.to_thread(rows.fetchall)

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
        return items

    async def save(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
        session_id: str = "",
    ) -> str:
        conn = await self._ensure_open()
        item_id = new_item_id()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        sql = """
            INSERT INTO memories (item_id, session_id, text, metadata, created_at)
            VALUES (?, ?, ?, ?, ?)
        """
        await asyncio.to_thread(
            conn.execute,
            sql,
            (item_id, session_id, text, meta_json, __import__("time").time()),
        )
        await asyncio.to_thread(conn.commit)
        return item_id

    async def delete(self, item_id: str) -> bool:
        conn = await self._ensure_open()
        sql = "DELETE FROM memories WHERE item_id = ?"
        cursor = await asyncio.to_thread(conn.execute, sql, (item_id,))
        await asyncio.to_thread(conn.commit)
        return cursor.rowcount > 0

    # --- 便利 -----------------------------------------------------------------

    async def count(self) -> int:
        conn = await self._ensure_open()
        sql = "SELECT COUNT(*) FROM memories"
        row = await asyncio.to_thread(conn.execute, sql)
        row = await asyncio.to_thread(row.fetchone)
        return int(row[0]) if row else 0

    async def clear(self) -> int:
        """清空全部记录，返回删除条数。主要用于测试。"""
        conn = await self._ensure_open()
        sql = "DELETE FROM memories"
        cursor = await asyncio.to_thread(conn.execute, sql)
        await asyncio.to_thread(conn.commit)
        return cursor.rowcount
