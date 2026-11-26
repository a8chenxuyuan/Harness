"""运行时指标公共入口。

后端选择：装了 prometheus-client 用 Prometheus，否则降级到内存 dict。
所有调用方只依赖本模块的函数，不感知后端差异。
"""

from __future__ import annotations

from typing import Any

from .http_stats import http_stats
from .metrics_backends import DictMetricsBackend, PromMetricsBackend


def _is_prometheus_available() -> bool:
    try:
        import prometheus_client  # noqa: F401
        return True
    except ImportError:
        return False


_PROM_AVAILABLE = _is_prometheus_available()

_backend: PromMetricsBackend | DictMetricsBackend = (
    PromMetricsBackend() if _PROM_AVAILABLE else DictMetricsBackend()
)


# ---------------------------------------------------------------------------
# 引擎指标
# ---------------------------------------------------------------------------


def record_cache_hit(hit: bool, session_id: str = "default") -> None:
    """记录一次缓存命中/未命中。"""
    _backend.record_cache_hit(hit, session_id)


def record_ttft(duration: float, session_id: str = "default") -> None:
    """记录一次首 token 延迟（秒）。"""
    _backend.record_ttft(duration, session_id)


def record_tool_duration(name: str, duration: float) -> None:
    """记录一次工具调用耗时（秒）。"""
    _backend.record_tool_duration(name, duration)


def record_loop_iteration(session_id: str = "default") -> None:
    """记录一次循环迭代。"""
    _backend.record_loop_iteration(session_id)


def record_compaction(session_id: str = "default") -> None:
    """记录一次上下文压缩触发。"""
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
    """记录一次失败任务重派。"""
    _backend.record_worker_redispatch(task_id, count)


def record_handoff(from_task: str, to_worker: str) -> None:
    """记录一次 handoff 移交。"""
    _backend.record_handoff(from_task, to_worker)


def record_worker_prefix_stable_rounds(rounds: int, worker_name: str = "") -> None:
    """记录 Worker 会话内前缀稳定轮次。"""
    _backend.record_worker_prefix_stable_rounds(rounds, worker_name)


def record_plan_approval_latency(seconds: float) -> None:
    """记录一次 Plan 闸门等待时长（秒）。"""
    _backend.record_plan_approval_latency(seconds)


def record_replan(plan_id: str) -> None:
    """记录一次 replan（高频说明拆解质量差）。"""
    _backend.record_replan(plan_id)


def record_sandbox_violation(reason: str = "unknown") -> None:
    """记录一次沙箱越界拦截（正常应恒为 0）。"""
    _backend.record_sandbox_violation(reason)


def record_model_retry(model: str, reason: str) -> None:
    """记录一次模型调用重试（reason: timeout / error）。"""
    _backend.record_model_retry(model, reason)


def record_model_circuit_open(model: str) -> None:
    """记录一次模型熔断打开。"""
    _backend.record_model_circuit_open(model)


# ---------------------------------------------------------------------------
# HTTP / 平台指标（Phase 23）
# ---------------------------------------------------------------------------


def record_http_request(
    method: str,
    path: str,
    status_code: int,
    duration: float,
    request_id: str = "-",
) -> None:
    """记录一次 HTTP 请求：先入进程内摘要，再写 Prometheus。

    Args:
        method: HTTP 方法。
        path: 路由模板（如 ``/api/v1/health``），避免原始路径导致标签爆炸。
        status_code: 响应状态码。
        duration: 请求耗时（秒）。
        request_id: 请求链路 id，用于最近错误列表定位。
    """
    http_stats.record(method, path, status_code, duration, request_id)
    _backend.record_http_request(method, path, status_code, duration)


def metrics_snapshot() -> dict[str, Any]:
    """返回 HTTP 指标摘要（供管理页轮询）。"""
    return http_stats.snapshot(prometheus_available=_PROM_AVAILABLE)


def expose_prometheus() -> str:
    """输出 Prometheus 文本格式指标。

    prometheus-client 已安装时导出全部注册指标；未安装时降级为
    仅包含 HTTP 汇总的文本，保证 ``/metrics`` 始终可被 scrape。
    """
    if _PROM_AVAILABLE:
        from prometheus_client import generate_latest

        return generate_latest().decode("utf-8")

    snapshot = metrics_snapshot()
    lines = [
        "# HELP harness_http_requests_total HTTP 请求数（降级视图）",
        "# TYPE harness_http_requests_total counter",
        f'harness_http_requests_total{{class="all"}} {snapshot["total_requests"]}',
    ]
    for name, value in snapshot["status_counts"].items():
        lines.append(f'harness_http_requests_total{{class="{name}"}} {value}')
    lines.extend(
        [
            "# HELP harness_http_request_duration_seconds HTTP 平均耗时（降级视图）",
            "# TYPE harness_http_request_duration_seconds gauge",
            f"harness_http_request_duration_seconds {round(snapshot['avg_ms'] / 1000, 6)}",
        ]
    )
    return "\n".join(lines) + "\n"


def expose_dict() -> dict[str, Any]:
    """暴露 dict 后端快照（Prometheus 后端返回空 dict）。"""
    if isinstance(_backend, DictMetricsBackend):
        return {
            key: (value.copy() if isinstance(value, dict) else list(value))
            for key, value in _backend.data.items()
        }
    return {}


__all__ = [
    "expose_dict",
    "expose_prometheus",
    "metrics_snapshot",
    "record_cache_hit",
    "record_compaction",
    "record_handoff",
    "record_http_request",
    "record_loop_iteration",
    "record_model_circuit_open",
    "record_model_retry",
    "record_orchestrator_dispatch",
    "record_plan_approval_latency",
    "record_replan",
    "record_resume_replay",
    "record_sandbox_violation",
    "record_tool_duration",
    "record_ttft",
    "record_worker_cache_hit",
    "record_worker_prefix_stable_rounds",
    "record_worker_redispatch",
    "record_worker_wall_seconds",
]
