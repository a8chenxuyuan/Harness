"""供应商缓存画像的兼容转发层。

Phase 3 起，画像的唯一定义方是 `harness.core.model.cache_profile`。本文件
只负责把同名符号重新导出，保证 Phase 2 已有的调用方
（`context/__init__.py`、`context/assembler.py` 以及任何外部用户代码）
无需改动导入路径。

为什么不直接把调用方都改成 `harness.core.model.cache_profile`：
    context 层在架构上属于「Phase 2 上下文装配」，Phase 3 之前就已经
    存在；贸然改所有 import 会让 Phase 2 的独立性被 Phase 3 反向污染。
    一个薄转发文件成本为零，同时保持分层清晰。
"""

from __future__ import annotations

from ..model.cache_profile import (
    CACHE_PROFILES,
    Breakpoint,
    CacheHints,
    CacheMode,
    CacheProfile,
    build_cache_hints,
    profile_for,
)

__all__ = [
    "CACHE_PROFILES",
    "Breakpoint",
    "CacheHints",
    "CacheMode",
    "CacheProfile",
    "build_cache_hints",
    "profile_for",
]
