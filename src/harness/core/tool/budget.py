"""工具预算：结果截断 + 调用去重。

- :data:`MAX_RESULT_BYTES`: 结果输出的默认上限。
- :func:`truncate_output`: 按字节截断，保留头部 40% / 尾部 60%。
- :class:`ToolBudget`: 把截断、去重缓存（带 TTL）打包在一起。

缓存 key 使用 ``(tool_name + sorted_json_args)``，保证同参同工具在 TTL 内
只会真实执行一次；后续命中直接返回缓存副本，并加注 ``(缓存命中，未重新执行)``。
"""

from __future__ import annotations

import json
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from .base import ToolResult

# 默认最大输出字节数（约 80 KB，足够绝大多数工具返回）
MAX_RESULT_BYTES = 80_000

# 去重 TTL 默认 5 分钟
_DEFAULT_DEDUP_TTL = 300


# ---------------------------------------------------------------------------
# 纯函数工具
# ---------------------------------------------------------------------------

def truncate_output(text: str, max_bytes: int = MAX_RESULT_BYTES) -> str:
    """按 UTF-8 字节截断文本。

    策略：保留前 40% 和后 60% 的字节，中间插入 ``... [truncated N bytes] ...``。
    若原始字节数 ≤ max_bytes 直接返回原串。

    Args:
        text: 原始输出。
        max_bytes: 上限字节数。

    Returns:
        截断后的文本（若未截断则原样返回）。
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text

    head_bytes = int(max_bytes * 0.4)
    tail_bytes = max_bytes - head_bytes
    head = encoded[:head_bytes].decode("utf-8", errors="replace")
    tail = encoded[-tail_bytes:].decode("utf-8", errors="replace")
    omitted = len(encoded) - max_bytes
    gap = f"\n... [truncated {omitted} bytes] ...\n"
    return head + gap + tail


def _dedup_key(tool_name: str, args: dict[str, Any]) -> str:
    """稳定化的去重 key：工具名 + 按参数名排序后的 JSON。"""
    sorted_args = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    return f"{tool_name}::{sorted_args}"


# ---------------------------------------------------------------------------
# ToolBudget
# ---------------------------------------------------------------------------

class ToolBudget(BaseModel):
    """把结果截断和调用去重打包在一起的预算器。

    实例化建议作为进程级单例——内部持有 dict 缓存。

    Attributes:
        max_bytes: 单次输出上限字节数。
        dedup_ttl_seconds: 去重条目 TTL。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    max_bytes: int = Field(default=MAX_RESULT_BYTES)
    dedup_ttl_seconds: int = Field(default=_DEFAULT_DEDUP_TTL)

    # 运行时私有字段：去重缓存。{key: (expire_at_monotonic, ToolResult)}
    _dedup_cache: dict[str, tuple[float, ToolResult]] = PrivateAttr(default_factory=dict)

    # --- 截断包装 --------------------------------------------------------------

    def wrap_result(self, result: ToolResult) -> ToolResult:
        """若 result.output 超出 max_bytes 则截断，并标记 truncated=True。"""
        if len(result.output.encode("utf-8")) <= self.max_bytes:
            return result
        truncated_text = truncate_output(result.output, self.max_bytes)
        return ToolResult(
            ok=result.ok,
            output=truncated_text,
            error=result.error,
            execution_time_ms=result.execution_time_ms,
            truncated=True,
        )

    # --- 去重缓存 --------------------------------------------------------------

    def _evict_expired(self, now: float) -> None:
        """惰性清理过期条目。每次 check_dedup / record_dedup 都会触发一次。"""
        expired_keys = [k for k, (expire_at, _) in self._dedup_cache.items() if expire_at <= now]
        for k in expired_keys:
            self._dedup_cache.pop(k, None)

    def check_dedup(self, name: str, args: dict[str, Any]) -> ToolResult | None:
        """检查 (name, args) 是否在 TTL 内命中过；命中返回加了标记的副本，未命中返回 None。"""
        now = time.monotonic()
        self._evict_expired(now)
        key = _dedup_key(name, args)
        hit = self._dedup_cache.get(key)
        if hit is None:
            return None
        _, result = hit
        # 返回副本并加注提示——ToolResult 是 frozen 的，用 model_copy 构造新实例
        marker = "(缓存命中，未重新执行)"
        if result.ok:
            new_output = result.output.rstrip() + f"\n{marker}"
            return ToolResult(
                ok=result.ok,
                output=new_output,
                error=result.error,
                execution_time_ms=0.0,  # 缓存命中视为 0ms
                truncated=result.truncated,
            )
        else:
            new_error = (result.error or "") + f" {marker}"
            return ToolResult(
                ok=False,
                output=result.output,
                error=new_error,
                execution_time_ms=0.0,
                truncated=result.truncated,
            )

    def record_dedup(self, name: str, args: dict[str, Any], result: ToolResult) -> None:
        """把一次真实执行结果记入去重缓存，TTL 到期自动清理。"""
        now = time.monotonic()
        self._evict_expired(now)
        key = _dedup_key(name, args)
        self._dedup_cache[key] = (now + self.dedup_ttl_seconds, result)

    # --- 调试 -----------------------------------------------------------------

    def cache_size(self) -> int:
        """当前去重缓存条目数（含过期未清理）。"""
        return len(self._dedup_cache)
