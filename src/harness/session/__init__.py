"""Phase 8：会话持久化层。

对外导出：
    - SessionTreeEntry：不可变记录（sqlite 行的内存镜像）
    - SessionStore：sqlite 追加存储（asyncio.to_thread 包装同步 sqlite3）
    - SessionWindow + derive_window：按 token 预算裁剪上下文窗口
    - CheckpointManager：AgentState 的 save / load / 工具去重
"""

from .checkpoint import CheckpointManager
from .entry import EntryKind, SessionTreeEntry
from .store import SessionStore
from .window import SessionWindow, derive_window

__all__ = [
    "CheckpointManager",
    "EntryKind",
    "SessionStore",
    "SessionTreeEntry",
    "SessionWindow",
    "derive_window",
]
