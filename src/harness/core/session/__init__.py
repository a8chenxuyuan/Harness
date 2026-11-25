"""Phase 8：会话持久化层。

对外导出：
    - SessionTreeEntry：不可变记录（sqlite 行的内存镜像）
    - SessionStore：sqlite 追加存储（Phase 0-21 兼容别名）
    - SessionStoreProtocol / SQLiteSessionStore / PostgresSessionStore：Phase 24 抽象与实现
    - create_session_store：按 URL 自动选择实现
    - SessionWindow + derive_window：按 token 预算裁剪上下文窗口
    - CheckpointManager：AgentState 的 save / load / 工具去重
"""

from .checkpoint import CheckpointManager
from .entry import EntryKind, SessionTreeEntry
from .pg_store import PostgresSessionStore
from .store import (
    SessionStore,
    SessionStoreProtocol,
    SQLiteSessionStore,
    create_session_store,
)
from .window import SessionWindow, derive_window

__all__ = [
    "CheckpointManager",
    "EntryKind",
    "PostgresSessionStore",
    "SessionStore",
    "SessionStoreProtocol",
    "SessionTreeEntry",
    "SessionWindow",
    "SQLiteSessionStore",
    "create_session_store",
    "derive_window",
]
