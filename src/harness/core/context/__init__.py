"""上下文层：装配、缓存断点、前缀守卫与 token 预算。

对外只导出装配所需的入口与数据模型，内部实现细节不导出。
"""

from .assembler import AssembledContext, ContextAssembler, StablePrefix
from .cache_policy import (
    Breakpoint,
    CacheHints,
    CacheMode,
    CacheProfile,
    build_cache_hints,
    profile_for,
)
from .prefix_guard import (
    PrefixChangeReason,
    PrefixCheckResult,
    PrefixGuard,
    PrefixStabilityError,
)
from .token_budget import TokenBudget, TokenBudgetStatus, TokenCounter, estimate_tokens

__all__ = [
    "AssembledContext",
    "Breakpoint",
    "CacheHints",
    "CacheMode",
    "CacheProfile",
    "ContextAssembler",
    "PrefixChangeReason",
    "PrefixCheckResult",
    "PrefixGuard",
    "PrefixStabilityError",
    "StablePrefix",
    "TokenBudget",
    "TokenBudgetStatus",
    "TokenCounter",
    "build_cache_hints",
    "estimate_tokens",
    "profile_for",
]
