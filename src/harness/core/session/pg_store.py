"""PostgreSQL 会话存储（Phase 24，方案 A）。

表结构 append-only：``session_entries(entry_id, seq, kind, content, created_at)``。
sessions 表只存元数据，会话历史按 entry 逐条追加，恢复时按 seq ASC 重放。

依赖：``postgresql+asyncpg://`` 或 ``postgresql+psycopg://`` 形式的 URL
（驱动需目标环境自行安装）。引擎懒初始化——只构造不连接。
"""

from __future__ import annotations

import asyncio
import logging

from .entry import SessionTreeEntry

log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    entry_id   VARCHAR(64) PRIMARY KEY,
    seq        BIGINT NOT NULL,
    kind       VARCHAR(32) NOT NULL,
    content    TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL
)
"""

_INSERT = """
INSERT INTO {table} (entry_id, seq, kind, content, created_at)
VALUES (:entry_id, :seq, :kind, :content, :created_at)
ON CONFLICT (entry_id) DO UPDATE SET
    seq = EXCLUDED.seq,
    kind = EXCLUDED.kind,
    content = EXCLUDED.content,
    created_at = EXCLUDED.created_at
"""


class PostgresSessionStore:
    """基于 PostgreSQL 的追加式会话存储。

    Attributes:
        _url: SQLAlchemy 异步 URL。
        _table: 表名（默认 session_entries）。
        _engine: 懒初始化的异步引擎。
    """

    def __init__(self, database_url: str, *, table: str = "session_entries") -> None:
        self._url = database_url
        self._table = table
        self._engine = None
        self._lock = asyncio.Lock()

    # --- 引擎 / 建表 ----------------------------------------------------------

    async def _ensure_engine(self):
        """懒创建引擎并保证表存在。"""
        if self._engine is not None:
            return self._engine
        async with self._lock:
            if self._engine is None:
                from sqlalchemy.ext.asyncio import create_async_engine

                engine = create_async_engine(self._url, echo=False, future=True)
                from sqlalchemy import text

                async with engine.begin() as conn:
                    await conn.execute(text(_DDL.format(table=self._table)))
                    await conn.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS ix_{self._table}_seq "
                            f"ON {self._table} (seq)"
                        )
                    )
                self._engine = engine
                log.info("PostgresSessionStore: 表 %s 就绪", self._table)
        return self._engine

    # --- 写入 -----------------------------------------------------------------

    async def _next_seq(self, conn) -> int:
        from sqlalchemy import text

        row = await conn.execute(
            text(f"SELECT COALESCE(MAX(seq), 0) FROM {self._table}")
        )
        return int(row.scalar_one()) + 1

    async def append(self, entry: SessionTreeEntry) -> SessionTreeEntry:
        """追加一条 entry（seq<=0 时自动分配 MAX(seq)+1）。"""
        engine = await self._ensure_engine()
        from sqlalchemy import text

        async with engine.begin() as conn:
            seq = entry.seq if entry.seq > 0 else await self._next_seq(conn)
            await conn.execute(
                text(_INSERT.format(table=self._table)),
                {
                    "entry_id": entry.entry_id,
                    "seq": seq,
                    "kind": entry.kind,
                    "content": entry.to_row()[3],
                    "created_at": entry.created_at,
                },
            )
        return SessionTreeEntry(
            entry_id=entry.entry_id,
            seq=seq,
            kind=entry.kind,  # type: ignore[arg-type]
            content=entry.content,
            created_at=entry.created_at,
        )

    async def append_many(
        self, entries: list[SessionTreeEntry]
    ) -> list[SessionTreeEntry]:
        """批量追加（单事务）。"""
        if not entries:
            return []
        engine = await self._ensure_engine()
        from sqlalchemy import text

        out: list[SessionTreeEntry] = []
        async with engine.begin() as conn:
            base = await self._next_seq(conn)
            for idx, entry in enumerate(entries):
                seq = entry.seq if entry.seq > 0 else base + idx
                await conn.execute(
                    text(_INSERT.format(table=self._table)),
                    {
                        "entry_id": entry.entry_id,
                        "seq": seq,
                        "kind": entry.kind,
                        "content": entry.to_row()[3],
                        "created_at": entry.created_at,
                    },
                )
                out.append(
                    SessionTreeEntry(
                        entry_id=entry.entry_id,
                        seq=seq,
                        kind=entry.kind,  # type: ignore[arg-type]
                        content=entry.content,
                        created_at=entry.created_at,
                    )
                )
        return out

    # --- 读取 -----------------------------------------------------------------

    async def _query(self, sql: str, params: dict | None = None) -> list[SessionTreeEntry]:
        engine = await self._ensure_engine()
        from sqlalchemy import text

        async with engine.connect() as conn:
            result = await conn.execute(text(sql), params or {})
            return [SessionTreeEntry.from_row(tuple(row)) for row in result.fetchall()]

    async def get_all(self) -> list[SessionTreeEntry]:
        """读全部 entry（seq ASC）。"""
        return await self._query(
            f"SELECT entry_id, seq, kind, content, created_at FROM {self._table} "
            "ORDER BY seq ASC"
        )

    async def get_by_seq_range(
        self, start: int, end: int | None = None
    ) -> list[SessionTreeEntry]:
        """读 [start, end]（end=None 无上限）。"""
        if end is None:
            return await self._query(
                f"SELECT entry_id, seq, kind, content, created_at FROM {self._table} "
                "WHERE seq >= :start ORDER BY seq ASC",
                {"start": start},
            )
        return await self._query(
            f"SELECT entry_id, seq, kind, content, created_at FROM {self._table} "
            "WHERE seq BETWEEN :start AND :end ORDER BY seq ASC",
            {"start": start, "end": end},
        )

    async def get_by_kind(self, kind: str) -> list[SessionTreeEntry]:
        """按 kind 过滤（seq ASC）。"""
        return await self._query(
            f"SELECT entry_id, seq, kind, content, created_at FROM {self._table} "
            "WHERE kind = :kind ORDER BY seq ASC",
            {"kind": kind},
        )

    async def max_seq(self) -> int:
        """当前最大 seq（空表为 0）。"""
        engine = await self._ensure_engine()
        from sqlalchemy import text

        async with engine.connect() as conn:
            row = await conn.execute(
                text(f"SELECT COALESCE(MAX(seq), 0) FROM {self._table}")
            )
            return int(row.scalar_one())

    # --- 清理 / 生命周期 -------------------------------------------------------

    async def delete_before_seq(self, seq: int) -> int:
        """删除 seq 小于阈值的 entry，返回删除行数。"""
        engine = await self._ensure_engine()
        from sqlalchemy import text

        async with engine.begin() as conn:
            result = await conn.execute(
                text(f"DELETE FROM {self._table} WHERE seq < :seq"), {"seq": seq}
            )
            return int(result.rowcount or 0)

    def close(self) -> None:
        """释放引擎（同步接口；有事件循环时异步 dispose）。"""
        engine, self._engine = self._engine, None
        if engine is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                asyncio.run(engine.dispose())
            except Exception:  # noqa: BLE001
                pass
        else:
            loop.create_task(engine.dispose())


__all__ = ["PostgresSessionStore"]
