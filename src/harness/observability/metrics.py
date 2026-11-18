"""运行时指标。

prometheus-client 是可选依赖——没装时用简单的内存 dict 模拟，
并提供一个 expose_dict() 方法返回当前快照，方便上层自己接
别的监控后端（如 Datadog、CloudWatch）。
"""

from __future__ import annotations

import time
from typing import Any

# ---------------------------------------------------------------------------
# 依赖检测
# ---------------------------------------------------------------------------


def _is_prometheus_available() -> bool:
    try:
        import prometheus_client  # noqa: F401
        return True
    except ImportError:
        return False


_PROM_AVAILABLE = _is_prometheus_available()


# ---------------------------------------------------------------------------
# Prometheus 真实现
# ---------------------------------------------------------------------------


class _PromMetricsBackend:
    """用 prometheus-client 做后端。"""

    def __init__(self) -> None:
        from prometheus_client import Counter, Gauge, Histogram

        # 全部 harness_ 前缀，避免撞名
        self.cache_hit_ratio = Gauge(
            "harness_cache_hit_ratio",
            "Prompt 缓存命中率（0.0-1.0）",
            ["session_id"],
        )
        self.ttft_seconds = Histogram(
            "harness_ttft_seconds",
            "首 token 延迟（秒）",
            ["session_id"],
        )
        self.tool_duration_seconds = Histogram(
            "harness_tool_duration_seconds",
            "工具调用耗时（秒）",
            ["tool_name"],
        )
        self.loop_iterations = Counter(
            "harness_loop_iterations",
            "ReAct 循环总迭代次数",
            ["session_id"],
        )
        self.compaction_triggered = Counter(
            "harness_compaction_triggered",
            "触发上下文压缩的次数",
            ["session_id"],
        )
        self.resume_replayed_tools = Counter(
            "harness_resume_replayed_tools",
            "resume 时重放的工具调用次数",
            ["session_id"],
        )

    def record_cache_hit(self, hit: bool, session_id: str) -> None:
        self.cache_hit_ratio.labels(session_id=session_id).set(1.0 if hit else 0.0)

    def record_ttft(self, duration: float, session_id: str) -> None:
        self.ttft_seconds.labels(session_id=session_id).observe(duration)

    def record_tool_duration(self, name: str, duration: float) -> None:
        self.tool_duration_seconds.labels(tool_name=name).observe(duration)

    def record_loop_iteration(self, session_id: str) -> None:
        self.loop_iterations.labels(session_id=session_id).inc()

    def record_compaction(self, session_id: str) -> None:
        self.compaction_triggered.labels(session_id=session_id).inc()

    def record_resume_replay(self, session_id: str, count: int) -> None:
        self.resume_replayed_tools.labels(session_id=session_id).inc(count)


# ---------------------------------------------------------------------------
# dict 降级实现
# ---------------------------------------------------------------------------


class _DictMetricsBackend:
    """prometheus-client 没装时的简单内存存储。"""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {
            "cache_hit_ratio": {},
            "ttft_seconds": [],
            "tool_duration_seconds": [],
            "loop_iterations": {},
            "compaction_triggered": {},
            "resume_replayed_tools": {},
        }

    def record_cache_hit(self, hit: bool, session_id: str) -> None:
        self.data["cache_hit_ratio"][session_id] = 1.0 if hit else 0.0

    def record_ttft(self, duration: float, session_id: str) -> None:
        self.data["ttft_seconds"].append({"session_id": session_id, "value": duration})

    def record_tool_duration(self, name: str, duration: float) -> None:
        self.data["tool_duration_seconds"].append({"tool_name": name, "value": duration})

    def record_loop_iteration(self, session_id: str) -> None:
        self.data["loop_iterations"][session_id] = (
            self.data["loop_iterations"].get(session_id, 0) + 1
        )

    def record_compaction(self, session_id: str) -> None:
        self.data["compaction_triggered"][session_id] = (
            self.data["compaction_triggered"].get(session_id, 0) + 1
        )

    def record_resume_replay(self, session_id: str, count: int) -> None:
        self.data["resume_replayed_tools"][session_id] = (
            self.data["resume_replayed_tools"].get(session_id, 0) + count
        )


# ---------------------------------------------------------------------------
# 全局 backend 与公共入口
# ---------------------------------------------------------------------------

_backend: _PromMetricsBackend | _DictMetricsBackend = (
    _PromMetricsBackend() if _PROM_AVAILABLE else _DictMetricsBackend()
)


def record_cache_hit(hit: bool, session_id: str = "default") -> None:
    """记录一次缓存命中/未命中。

    Args:
        hit: True 表示命中。
        session_id: 会话标识。
    """
    _backend.record_cache_hit(hit, session_id)


def record_ttft(duration: float, session_id: str = "default") -> None:
    """记录一次首 token 延迟。

    Args:
        duration: 秒。
        session_id: 会话标识。
    """
    _backend.record_ttft(duration, session_id)


def record_tool_duration(name: str, duration: float) -> None:
    """记录一次工具调用耗时。

    Args:
        name: 工具名。
        duration: 秒。
    """
    _backend.record_tool_duration(name, duration)


def record_loop_iteration(session_id: str = "default") -> None:
    """记录一次循环迭代。"""
    _backend.record_loop_iteration(session_id)


def record_compaction(session_id: str = "default") -> None:
    """记录一次压缩触发。"""
    _backend.record_compaction(session_id)


def record_resume_replay(session_id: str, count: int = 1) -> None:
    """记录一次 resume 时重放的工具数量。"""
    _backend.record_resume_replay(session_id, count)


def expose_dict() -> dict[str, Any]:
    """暴露当前指标快照（仅 dict backend 有效；prometheus backend 返回空 dict）。

    Returns:
        指标名 → 当前值的字典。
    """
    if isinstance(_backend, _DictMetricsBackend):
        # 浅拷贝防止外部误改
        return {
            k: (v.copy() if isinstance(v, dict) else list(v))
            for k, v in _backend.data.items()
        }
    return {}
