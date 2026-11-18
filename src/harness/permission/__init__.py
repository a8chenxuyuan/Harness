"""权限系统（Phase 9 - Permission）。

对外导出：
    * PermissionMode —— 五种安全档位枚举
    * PermissionRule —— 单条权限规则
    * PermissionEngine —— 规则匹配引擎
    * PermissionDecision —— 评估结果
"""

from .engine import PermissionDecision, PermissionEngine
from .mode import PermissionMode
from .rule import PermissionRule

__all__ = [
    "PermissionDecision",
    "PermissionEngine",
    "PermissionMode",
    "PermissionRule",
]
