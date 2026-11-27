"""请求上下文中间件：request_id 贯穿 + HTTP 指标采集 + 访问日志。

执行顺序（Starlette 从外到内）：CORS → RequestContext → 路由。
- 优先复用客户端传入的 ``X-Request-ID``（便于跨服务串联），否则生成
- 响应统一回写 ``X-Request-ID``，方便前端 / 网关定位问题
- 每个请求写一条结构化访问日志，并记录 Prometheus / 进程内摘要指标
"""

from __future__ import annotations

import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from harness.common.observability.context import (
    bind_structlog_context,
    reset_request_id,
    set_request_id,
    unbind_structlog_context,
)
from harness.common.observability.logging import get_logger
from harness.common.observability.metrics import record_http_request
from harness.common.observability.tracing import start_span

log = get_logger("harness.access")

_MAX_REQUEST_ID_LENGTH = 64
_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """为每个 HTTP 请求建立 request_id 上下文并采集指标。"""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = _resolve_request_id(request)
        token = set_request_id(request_id)
        bind_structlog_context(request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            with start_span(
                "http.request",
                {"http.method": request.method, "http.path": _metric_path(request)},
            ) as span:
                response = await call_next(request)
                status_code = response.status_code
                span.set_attribute("http.status_code", status_code)
            response.headers[_HEADER] = request_id
            return response
        finally:
            duration = time.perf_counter() - started
            path = _metric_path(request)
            record_http_request(
                request.method, path, status_code, duration, request_id
            )
            log.info(
                "http_request",
                request_id=request_id,
                method=request.method,
                path=path,
                status=status_code,
                duration_ms=round(duration * 1000, 2),
            )
            unbind_structlog_context()
            reset_request_id(token)


def _resolve_request_id(request: Request) -> str:
    """取客户端 request_id（截断防注入），没有则生成。"""
    value = (request.headers.get(_HEADER) or "").strip()
    if not value:
        return f"req-{uuid.uuid4().hex[:16]}"
    return value[:_MAX_REQUEST_ID_LENGTH]


def _metric_path(request: Request) -> str:
    """把路径参数替换成 ``{name}``，作为指标标签避免基数爆炸。

    不依赖 ``scope['route'].path``：不同 FastAPI 版本下该值可能是
    子路由相对路径（缺 ``/api/v1`` 前缀），从真实 URL 回填更稳定。
    """
    path = request.url.path
    for name, value in (request.path_params or {}).items():
        # SPA 兜底路由（full_path）不做模板化：/api 未命中 404 时
        # 需保留真实路径，供访问日志 / 追踪定位
        if name == "full_path":
            continue
        if value:
            path = path.replace(str(value), "{" + name + "}")
    return path


__all__ = ["RequestContextMiddleware"]
