"""会话持久化存储：sqlite3 + asyncio.to_thread。

为什么不用 langgraph-checkpoint-sqlite？
    - Phase 8 的 checkpoint 只需要"追加式 + 按 seq 重放"两个能力，
      不需要 langgraph 的 Blob / JSON 重放；自己写约 200 行更可控。
    - entry 一旦写入永远不改不删——重放语义极简，恢复逻辑直接按 seq ASC 遍历。
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from .entry import SessionTreeEntry

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    entry_id   TEXT PRIMARY KEY,
    seq        INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_seq ON entries(seq);
"""
"""唯一表结构。entry 不可变——INSERT OR REPLACE 只是保证 entry_id 冲突时不会抛错。"""


class SessionStore:
    """基于 sqlite3 的 SessionTreeEntry 追加存储。

    并发模型：sqlite3 自己就不能跨线程共享连接，所以所有同步方法
    都包在 asyncio.to_thread 里串行执行。写入量不大（每轮几十条），
    单线程 sqlite 足够快。
    """

    def __init__(self, db_path: str | Path, init_db: bool = True) -> None:
        """打开（或新建）一个 sqlite 文件。

        Args:
            db_path: sqlite 文件路径。":memory:" 会建内存库，仅供测试。
            init_db: True 时自动 CREATE TABLE。False 假设表已经存在。
        """
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        if init_db:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # --- 写入 ------------------------------------------------------------------

    def _next_seq_sync(self) -> int:
        """同步取下一个 seq：如果库空就从 1 开始，否则 MAX(seq)+1。"""
        cur = self._conn.execute("SELECT COALESCE(MAX(seq), 0) FROM entries")
        row = cur.fetchone()
        return (row[0] if row else 0) + 1

    def _append_sync(self, entry: SessionTreeEntry) -> SessionTreeEntry:
        """同步追加一条 entry。entry.seq 为 0 时自动分配。"""
        seq = entry.seq if entry.seq > 0 else self._next_seq_sync()
        row = entry.to_row()
        # 用分配好的 seq 覆盖原 row[1]——frozen dataclass 不改对象本身。
        self._conn.execute(
            "INSERT OR REPLACE INTO entries(entry_id, seq, kind, content, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (row[0], seq, row[2], row[3], row[4]),
        )
        self._conn.commit()
        # 返回一个带正确 seq 的新实例，让调用方拿到完整 entry。
        return SessionTreeEntry(
            entry_id=entry.entry_id,
            seq=seq,
            kind=entry.kind,  # type: ignore[arg-type]
            content=entry.content,
            created_at=entry.created_at,
        )

    def _append_many_sync(self, entries: Sequence[SessionTreeEntry]) -> list[SessionTreeEntry]:
        """批量追加。同一次 commit，减少 I/O。"""
        if not entries:
            return []
        base = self._next_seq_sync()
        out: list[SessionTreeEntry] = []
        rows: list[tuple[str, int, str, str, float]] = []
        for idx, entry in enumerate(entries):
            seq = entry.seq if entry.seq > 0 else base + idx
            row = entry.to_row()
            rows.append((row[0], seq, row[2], row[3], row[4]))
            out.append(
                SessionTreeEntry(
                    entry_id=entry.entry_id,
                    seq=seq,
                    kind=entry.kind,  # type: ignore[arg-type]
                    content=entry.content,
                    created_at=entry.created_at,
                )
            )
        self._conn.executemany(
            "INSERT OR REPLACE INTO entries(entry_id, seq, kind, content, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()
        return out

    async def append(self, entry: SessionTreeEntry) -> SessionTreeEntry:
        """异步追加一条 entry。

        Args:
            entry: 待写入的 entry。seq=0 时自动分配。

        Returns:
            分配好 seq 的完整 entry（同 entry_id）。
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._append_sync, entry)

    async def append_many(self, entries: Iterable[SessionTreeEntry]) -> list[SessionTreeEntry]:
        """异步批量追加。适合 save() 一次性刷完整轮 messages。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._append_many_sync, list(entries))

    # --- 读取 ------------------------------------------------------------------

    def _query_sync(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> list[SessionTreeEntry]:
        cur = self._conn.execute(sql, params)
        return [SessionTreeEntry.from_row(tuple(r)) for r in cur.fetchall()]

    async def get_all(self) -> list[SessionTreeEntry]:
        """读全部 entry，按 seq ASC。恢复时重放用这个。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._query_sync, "SELECT * FROM entries ORDER BY seq ASC", ()
        )

    async def get_by_seq_range(
        self, start: int, end: int | None = None
    ) -> list[SessionTreeEntry]:
        """读 [start, end] 的 entry；end=None 表示无上限。"""
        if end is None:
            sql = "SELECT * FROM entries WHERE seq >= ? ORDER BY seq ASC"
            params: tuple[Any, ...] = (start,)
        else:
            sql = "SELECT * FROM entries WHERE seq BETWEEN ? AND ? ORDER BY seq ASC"
            params = (start, end)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._query_sync, sql, params)

    async def get_by_kind(self, kind: str) -> list[SessionTreeEntry]:
        """按 kind 过滤，仍按 seq ASC。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._query_sync, "SELECT * FROM entries WHERE kind = ? ORDER BY seq ASC", (kind,)
        )

    async def max_seq(self) -> int:
        """当前最大 seq；库空时返回 0。"""
        def _sync() -> int:
            cur = self._conn.execute("SELECT COALESCE(MAX(seq), 0) FROM entries")
            row = cur.fetchone()
            return int(row[0]) if row else 0

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync)

    # --- 清理 ------------------------------------------------------------------

    def _delete_before_seq_sync(self, seq: int) -> int:
        """删除 seq < 阈值的 entry。返回删除行数。

        压缩是追加式的：compaction entry 本身不会被删——只有当同一区间
        已经被更高层的 compaction 覆盖、且保留了摘要后，才可以显式清旧
        message/compaction。这个清理方法只在 CheckpointManager 显式调用时
        触发，不会在 append 时自动执行。
        """
        cur = self._conn.execute("DELETE FROM entries WHERE seq < ?", (seq,))
        self._conn.commit()
        return cur.rowcount

    async def delete_before_seq(self, seq: int) -> int:
        """清理 seq < 阈值的旧 entry。返回删除行数。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._delete_before_seq_sync, seq)

    # --- 生命周期 --------------------------------------------------------------

    def close(self) -> None:
        """关闭 sqlite 连接。重复调用安全。"""
        try:
            self._conn.close()
        except sqlite3.Error:
            pass
