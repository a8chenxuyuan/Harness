"""权限模式枚举。

PermissionMode 定义了 harness 运行时的五种安全档位，
从完全只读（EXPLORE）到完全放行（TRUSTED），
供 PermissionEngine 选择对应的内置规则集。
"""

from __future__ import annotations

from enum import Enum


class PermissionMode(str, Enum):
    """权限模式——决定写工具何时被允许、何时被拦截、何时需要人工确认。

    Attributes:
        EXPLORE: 只读放行，所有写工具一律 DENY；适合开发/探索阶段。
        DEFAULT: 只读放行，写工具统一 ASK（HITL）；默认安全模式。
        AGENTIC: 只读 + 低风险写放行（如 create_file），高风险写 ASK。
        TRUSTED: 全部放行；仅限本地可信场景。
        LOCKDOWN: 全部 DENY；紧急止损。
    """

    EXPLORE = "explore"
    DEFAULT = "default"
    AGENTIC = "agentic"
    TRUSTED = "trusted"
    LOCKDOWN = "lockdown"
