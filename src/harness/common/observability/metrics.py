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
        # --- 编排层（Phase 18） ---
        self.orchestrator_dispatch_total = Counter(
            "harness_orchestrator_dispatch_total", "编排器派发任务次数", ["coordinator_id"],
        )
        self.worker_wall_seconds = Histogram(
            "harness_worker_wall_seconds", "单 Worker 任务墙钟（秒）", ["worker_name"],
        )
        self.worker_cache_hit_ratio = Gauge(
            "harness_worker_cache_hit_ratio", "Worker 缓存命中率", ["worker_name"],
        )
        self.worker_redispatch_total = Counter(
            "harness_worker_redispatch_total", "失败任务重派次数", ["task_id"],
        )
        self.handoff_total = Counter(
            "harness_handoff_total", "handoff 移交次数", ["from_task", "to_worker"],
        )
        self.worker_prefix_stable_rounds = Gauge(
            "harness_worker_prefix_stable_rounds", "Worker 前缀稳定轮次", ["worker_name"],
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

    def record_orchestrator_dispatch(self, count: int, coordinator_id: str) -> None:
        self.orchestrator_dispatch_total.labels(coordinator_id=coordinator_id).inc(count)

    def record_worker_wall_seconds(self, seconds: float, worker_name: str) -> None:
        self.worker_wall_seconds.labels(worker_name=worker_name).observe(seconds)

    def record_worker_cache_hit(self, ratio: float, worker_name: str) -> None:
        self.worker_cache_hit_ratio.labels(worker_name=worker_name).set(ratio)

    def record_worker_redispatch(self, task_id: str, count: int = 1) -> None:
        self.worker_redispatch_total.labels(task_id=task_id).inc(count)

    def record_handoff(self, from_task: str, to_worker: str) -> None:
        self.handoff_total.labels(from_task=from_task, to_worker=to_worker).inc()

    def record_worker_prefix_stable_rounds(self, rounds: int, worker_name: str) -> None:
        self.worker_prefix_stable_rounds.labels(worker_name=worker_name).set(rounds)


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
            # --- 编排层（Phase 18） ---
            "orchestrator_dispatch_total": {},
            "worker_wall_seconds": [],
            "worker_cache_hit_ratio": {},
            "worker_redispatch_total": {},
            "handoff_total": {},
            "worker_prefix_stable_rounds": {},
            # --- P19 Plan 指标 ---
            "plan_approval_latency": [],
            "replan_total": {},
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

    def record_orchestrator_dispatch(self, count: int, coordinator_id: str) -> None:
        key = self.data["orchestrator_dispatch_total"]
        key[coordinator_id] = key.get(coordinator_id, 0) + count

    def record_worker_wall_seconds(self, seconds: float, worker_name: str) -> None:
        self.data["worker_wall_seconds"].append(
            {"worker_name": worker_name, "value": seconds}
        )

    def record_worker_cache_hit(self, ratio: float, worker_name: str) -> None:
        self.data["worker_cache_hit_ratio"][worker_name] = ratio

    def record_worker_redispatch(self, task_id: str, count: int = 1) -> None:
        key = self.data["worker_redispatch_total"]
        key[task_id] = key.get(task_id, 0) + count

    def record_handoff(self, from_task: str, to_worker: str) -> None:
        pair = f"{from_task}->{to_worker}"
        key = self.data["handoff_total"]
        key[pair] = key.get(pair, 0) + 1

    def record_worker_prefix_stable_rounds(self, rounds: int, worker_name: str) -> None:
        self.data["worker_prefix_stable_rounds"][worker_name] = rounds

    def record_plan_approval_latency(self, seconds: float) -> None:
        self.data["plan_approval_latency"].append(seconds)

    def record_replan(self, plan_id: str) -> None:
        key = self.data["replan_total"]
        key[plan_id] = key.get(plan_id, 0) + 1


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


def record_orchestrator_dispatch(count: int = 1, coordinator_id: str = "default") -> None:
    """编排器记一次（批）任务派发。"""
    _backend.record_orchestrator_dispatch(count, coordinator_id)


def record_worker_wall_seconds(seconds: float, worker_name: str = "") -> None:
    """记录单 Worker 任务墙钟（秒）。"""
    _backend.record_worker_wall_seconds(seconds, worker_name)


def record_worker_cache_hit(ratio: float, worker_name: str = "") -> None:
    """记录 Worker 缓存命中率快照（0.0-1.0）。"""
    _backend.record_worker_cache_hit(ratio, worker_name)


def record_worker_redispatch(task_id: str, count: int = 1) -> None:
    """记一次失败任务重派。"""
    _backend.record_worker_redispatch(task_id, count)


def record_handoff(from_task: str, to_worker: str) -> None:
    """记一次 handoff 移交。"""
    _backend.record_handoff(from_task, to_worker)


def record_worker_prefix_stable_rounds(rounds: int, worker_name: str = "") -> None:
    """记录 Worker 会话内前缀稳定轮次。"""
    _backend.record_worker_prefix_stable_rounds(rounds, worker_name)


def record_plan_approval_latency(seconds: float) -> None:
    """记录一次 Plan 闸门等待时长（秒）。"""
    _backend.record_plan_approval_latency(seconds)


def record_replan(plan_id: str) -> None:
    """记一次 replan（预期低频；高频说明拆解质量差）。"""
    _backend.record_replan(plan_id)


def record_sandbox_violation(reason: str = "unknown") -> None:
    """记一次沙箱越界拦截（正常应为 0 才算干净跑完）。"""
    # Dict backend 里用 violation 类型作 key 累计
    bucket = _backend.data.setdefault("sandbox_violation_total", {})
    bucket[reason] = bucket.get(reason, 0) + 1


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
