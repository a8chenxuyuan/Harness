"""请求级上下文：request_id 的存取、日志注入与 structlog 绑定。

一个请求进入后由 ``RequestContextMiddleware`` 写入 ContextVar；
handler / service / 审计 / 日志都从这里读取，实现「一个 id 串起整条链路」。
"""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token

# 未进入请求上下文（如启动阶段、后台任务）时的占位值
DEFAULT_REQUEST_ID = "-"

_request_id: ContextVar[str] = ContextVar("request_id", default=DEFAULT_REQUEST_ID)


def get_request_id() -> str:
    """返回当前请求的 request_id；不在请求上下文时返回 ``-``。"""
    return _request_id.get()


def set_request_id(value: str) -> Token:
    """写入 request_id，返回可用于恢复的 token。"""
    return _request_id.set(value)


def reset_request_id(token: Token) -> None:
    """恢复上一个 request_id（请求结束时调用）。"""
    _request_id.reset(token)


class RequestIdFilter(logging.Filter):
    """给标准 logging 记录注入 request_id，供 formatter 使用。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


def bind_structlog_context(request_id: str) -> None:
    """structlog 可用时把 request_id 绑定到 contextvars（JSON 日志自动带上）。"""
    try:
        import structlog
    except ImportError:
        return
    structlog.contextvars.bind_contextvars(request_id=request_id)


def unbind_structlog_context() -> None:
    """请求结束时清理 structlog 上下文，避免串到下一条请求。"""
    try:
        import structlog
    except ImportError:
        return
    structlog.contextvars.unbind_contextvars("request_id")


__all__ = [
    "DEFAULT_REQUEST_ID",
    "RequestIdFilter",
    "bind_structlog_context",
    "get_request_id",
    "reset_request_id",
    "set_request_id",
    "unbind_structlog_context",
]
