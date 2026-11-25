"""HITL 会话持久化（SQLite）。

HitlStorage 提供 async 接口，内部用 sqlite3 同步调用通过 asyncio.to_thread
包装。支持重启后从数据库恢复 pending session。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from typing import Literal

from .manager import HitlSession


class HitlStorage:
    """HITL session 的 SQLite 持久化层。

    Attributes:
        db_path: 数据库文件路径。
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS hitl_sessions (
        request_id       TEXT PRIMARY KEY,
        tool_name        TEXT NOT NULL,
        args             TEXT NOT NULL,
        decision         TEXT,
        reason           TEXT,
        status           TEXT NOT NULL DEFAULT 'pending',
        created_at       REAL NOT NULL,
        user_response_at REAL
    )
    """

    def __init__(self, db_path: str) -> None:
        """初始化并打开数据库连接。

        Args:
            db_path: SQLite 文件路径（内存库可用 ``":memory:"``）。
        """
        self.db_path: str = db_path
        self._local = threading.local()  # 每个线程独立连接
        conn = self._get_conn()
        conn.execute(self._SCHEMA)
        conn.commit()

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        """获取当前线程的 sqlite3 连接。"""
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    # ------------------------------------------------------------------
    # async 公共接口
    # ------------------------------------------------------------------

    async def save(self, session: HitlSession) -> None:
        """保存或覆盖一条 session。

        Args:
            session: 要持久化的 HitlSession。
        """
        import asyncio

        def _sync() -> None:
            conn = self._get_conn()
            conn.execute(
                """
                INSERT INTO hitl_sessions
                    (request_id, tool_name, args, decision, reason, status,
                     created_at, user_response_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    tool_name=excluded.tool_name,
                    args=excluded.args,
                    decision=excluded.decision,
                    reason=excluded.reason,
                    status=excluded.status,
                    created_at=excluded.created_at,
                    user_response_at=excluded.user_response_at
                """,
                (
                    session.request_id,
                    session.tool_name,
                    json.dumps(session.args, ensure_ascii=False),
                    session.decision,
                    session.reason,
                    session.status,
                    session.created_at,
                    session.user_response_at,
                ),
            )
            conn.commit()

        await asyncio.to_thread(_sync)

    async def get(self, request_id: str) -> HitlSession | None:
        """按 id 查询 session。

        Args:
            request_id: HITL 请求 id。

        Returns:
            命中的 HitlSession；不存在则返回 None。
        """
        import asyncio

        def _sync() -> HitlSession | None:
            row = self._get_conn().execute(
                "SELECT * FROM hitl_sessions WHERE request_id = ?", (request_id,)
            ).fetchone()
            return self._row_to_session(row) if row else None

        return await asyncio.to_thread(_sync)

    async def get_pending(self) -> list[HitlSession]:
        """列出所有 pending 状态的 session。

        Returns:
            HitlSession 列表（按 created_at 升序）。
        """
        import asyncio

        def _sync() -> list[HitlSession]:
            rows = self._get_conn().execute(
                "SELECT * FROM hitl_sessions WHERE status = 'pending' ORDER BY created_at ASC"
            ).fetchall()
            return [self._row_to_session(r) for r in rows]

        return await asyncio.to_thread(_sync)

    def close(self) -> None:
        """关闭当前线程持有的连接。"""
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            del self._local.conn

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> HitlSession:
        """将 sqlite3.Row 转换为 HitlSession。"""
        return HitlSession(
            request_id=row["request_id"],
            tool_name=row["tool_name"],
            args=json.loads(row["args"]),
            decision=row["decision"],
            reason=row["reason"],
            status=row["status"],
            created_at=row["created_at"],
            user_response_at=row["user_response_at"],
        )
