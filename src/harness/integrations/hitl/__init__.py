"""HITL 系统（Phase 9 - Human-In-The-Loop）。

对外导出：
    * HitlManager —— HITL 会话总控（pending → approve/deny）
    * HitlSession —— 一次待人工确认的完整上下文
"""

from .manager import HitlManager, HitlSession

__all__ = [
    "HitlManager",
    "HitlSession",
]
