"""观测层（Phase 11）。

对外导出 tracing / metrics / logging 三套件。所有可选依赖未装时
都有优雅降级的 no-op 实现，不会让主流程 import 失败。
"""

from .logging import get_logger
from .metrics import (
    expose_dict,
    expose_prometheus,
    metrics_snapshot,
    record_cache_hit,
    record_compaction,
    record_http_request,
    record_loop_iteration,
    record_resume_replay,
    record_tool_duration,
    record_ttft,
)
from .tracing import end_span, init_otel, start_span

__all__ = [
    # logging
    "get_logger",
    # metrics
    "expose_dict",
    "expose_prometheus",
    "metrics_snapshot",
    "record_cache_hit",
    "record_compaction",
    "record_http_request",
    "record_loop_iteration",
    "record_resume_replay",
    "record_tool_duration",
    "record_ttft",
    # tracing
    "end_span",
    "init_otel",
    "start_span",
]
