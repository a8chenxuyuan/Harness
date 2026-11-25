"""模型适配层的对外导出。

本包把 Phase 3 里所有与大模型交互相关的组件集中暴露出来：
通用数据结构 types、供应商缓存画像 cache_profile、抽象基类 base，
以及两个具体的适配器 OpenAICompat / AnthropicModel。
"""

from .base import Model, ModelCapabilities
from .cache_profile import (
    CACHE_PROFILES,
    Breakpoint,
    CacheHints,
    CacheMode,
    CacheProfile,
    build_cache_hints,
    profile_for,
)
from .types import (
    ChatChunk,
    ChatResponse,
    GenerateOptions,
    ToolCall,
    ToolCallDelta,
    Usage,
)

__all__ = [
    # base
    "Model",
    "ModelCapabilities",
    # cache_profile
    "CACHE_PROFILES",
    "Breakpoint",
    "CacheHints",
    "CacheMode",
    "CacheProfile",
    "build_cache_hints",
    "profile_for",
    # types
    "ChatChunk",
    "ChatResponse",
    "GenerateOptions",
    "ToolCall",
    "ToolCallDelta",
    "Usage",
]


# 具体适配器在 import 时会建立循环（它们依赖 Model ABC），延后导入。
# 上层按需 import harness.core.model.openai_compat 或 harness.core.model.anthropic。
