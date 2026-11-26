"""进程内 HTTP 统计（与 Prometheus 后端解耦）。

管理页摘要接口读这份快照；``/metrics`` 的 Prometheus 数据由 metrics 模块输出。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

# 延迟分位采样窗口（只保留最近 N 次，避免无限增长）
_DURATION_SAMPLE = 500
_RECENT_ERROR_LIMIT = 10


class HttpStats:
    """HTTP 请求统计：总量、状态分布、延迟分位、最近错误。"""

    def __init__(self) -> None:
        self.started_at = time.time()
        self.total = 0
        self.error_total = 0
        self.status_counts = {
            "ok": 0,
            "redirect": 0,
            "client_error": 0,
            "server_error": 0,
        }
        self.duration_sum = 0.0
        self.durations: deque[float] = deque(maxlen=_DURATION_SAMPLE)
        self.recent_errors: deque[dict[str, Any]] = deque(
            maxlen=_RECENT_ERROR_LIMIT
        )
        self.lock = threading.Lock()

    def record(
        self,
        method: str,
        path: str,
        status_code: int,
        duration: float,
        request_id: str,
    ) -> None:
        """记一次请求（线程安全）。"""
        with self.lock:
            self.total += 1
            self.duration_sum += duration
            self.durations.append(duration)
            if 200 <= status_code < 300:
                self.status_counts["ok"] += 1
            elif 300 <= status_code < 400:
                self.status_counts["redirect"] += 1
            elif 400 <= status_code < 500:
                self.status_counts["client_error"] += 1
                self.error_total += 1
            elif status_code >= 500:
                self.status_counts["server_error"] += 1
                self.error_total += 1
            if status_code >= 400:
                self.recent_errors.appendleft(
                    {
                        "time": _now_iso(),
                        "method": method,
                        "path": path,
                        "status": status_code,
                        "duration_ms": round(duration * 1000, 2),
                        "request_id": request_id,
                    }
                )

    def snapshot(self, *, prometheus_available: bool) -> dict[str, Any]:
        """返回指标摘要（供管理页与降级 /metrics 使用）。"""
        with self.lock:
            samples = sorted(self.durations)
            avg_ms = (self.duration_sum / self.total * 1000) if self.total else 0.0
            p95_ms = 0.0
            if samples:
                p95_ms = samples[int(0.95 * (len(samples) - 1))] * 1000
            return {
                "total_requests": self.total,
                "error_requests": self.error_total,
                "error_rate": round(self.error_total / self.total, 4)
                if self.total
                else 0.0,
                "avg_ms": round(avg_ms, 2),
                "p95_ms": round(p95_ms, 2),
                "status_counts": dict(self.status_counts),
                "recent_errors": list(self.recent_errors),
                "uptime_seconds": round(time.time() - self.started_at, 1),
                "prometheus_available": prometheus_available,
            }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


http_stats = HttpStats()


__all__ = ["HttpStats", "http_stats"]
