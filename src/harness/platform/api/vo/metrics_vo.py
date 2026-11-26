"""可观测指标 VO — 管理页轮询用的 HTTP 指标摘要。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HttpStatusCounts(BaseModel):
    """按状态类分组的请求数。"""

    ok: int = 0
    redirect: int = 0
    client_error: int = 0
    server_error: int = 0


class RecentHttpError(BaseModel):
    """最近一条失败请求（4xx / 5xx）。"""

    time: str
    method: str
    path: str
    status: int
    duration_ms: float
    request_id: str


class MetricsSummary(BaseModel):
    """GET /api/v1/observability/metrics 响应体。"""

    total_requests: int = 0
    error_requests: int = 0
    error_rate: float = 0.0
    avg_ms: float = 0.0
    p95_ms: float = 0.0
    status_counts: HttpStatusCounts = Field(default_factory=HttpStatusCounts)
    recent_errors: list[RecentHttpError] = Field(default_factory=list)
    uptime_seconds: float = 0.0
    prometheus_available: bool = False


__all__ = ["HttpStatusCounts", "MetricsSummary", "RecentHttpError"]
