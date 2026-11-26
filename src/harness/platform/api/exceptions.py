"""统一异常处理（对应 Java Spring 的 @ControllerAdvice）。

把业务层抛的异常统一转成标准 JSON 响应，避免每个 Controller
自己 try/except 又造一遍 HTTPException。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from harness.platform.api.vo.envelope_vo import ApiErrorResponse

log = logging.getLogger(__name__)


class BizError(Exception):
    """业务异常（Service 层可以直接 raise，Controller 不需要 catch）。

    Attributes:
        code: 业务错误码（前端可以据此分支处理）。
        message: 给用户看的简短错误描述。
        detail: 可选的详细信息（log 里打、API response 里透出）。
        status_code: HTTP 状态码。缺省回退到 ``code``（401/404/409 语义
            直接透传），都不合法时兜底 400。
    """

    def __init__(
        self,
        code: int,
        message: str,
        detail: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail
        self.status_code = status_code or code

    @property
    def http_status(self) -> int:
        """合法的 HTTP 状态码（非法业务码兜底 400）。"""
        if 400 <= self.status_code < 600:
            return self.status_code
        return 400


class RateLimitError(BizError):
    """限流异常：固定 429，并携带 Retry-After 响应头。"""

    def __init__(self, message: str, *, retry_after: float = 1.0) -> None:
        super().__init__(429, message)
        self.retry_after = max(1, int(retry_after + 0.999))


def register_exception_handlers(app: FastAPI) -> None:
    """在 FastAPI app 上注册所有异常处理器。

    Args:
        app: 目标 FastAPI 实例。
    """

    @app.exception_handler(BizError)
    async def _biz_error_handler(request: Request, exc: BizError) -> JSONResponse:
        log.warning("BizError: code=%s msg=%s detail=%s", exc.code, exc.message, exc.detail)
        return JSONResponse(
            status_code=exc.http_status,
            content=ApiErrorResponse(
                code=exc.code, message=exc.message, detail=exc.detail
            ).model_dump(),
        )

    @app.exception_handler(RateLimitError)
    async def _rate_limit_handler(request: Request, exc: RateLimitError) -> JSONResponse:
        log.warning("RateLimitError: msg=%s retry_after=%s", exc.message, exc.retry_after)
        return JSONResponse(
            status_code=429,
            content=ApiErrorResponse(code=429, message=exc.message).model_dump(),
            headers={"Retry-After": str(exc.retry_after)},
        )

    @app.exception_handler(HTTPException)
    async def _http_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ApiErrorResponse(
                code=exc.status_code, message=str(exc.detail)
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def _unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
        # 生产环境只给 500 + 通用消息；完整栈打日志
        log.exception("unexpected error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=ApiErrorResponse(code=500, message="internal server error").model_dump(),
        )


__all__ = ["BizError", "RateLimitError", "register_exception_handlers"]
