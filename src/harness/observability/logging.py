"""结构化日志。

structlog 是可选依赖——没装时降级到标准 logging，格式仍是
``[session_id=xxx step=N] message``，关键信息不会丢。
"""

from __future__ import annotations

import logging
import sys
from typing import Any


def _is_structlog_available() -> bool:
    try:
        import structlog  # noqa: F401
        return True
    except ImportError:
        return False


_STRUCTLOG_AVAILABLE = _is_structlog_available()

# ---------------------------------------------------------------------------
# 全局初始化（进程内只做一次）
# ---------------------------------------------------------------------------

_initialized = False


def _ensure_initialized() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True

    if _STRUCTLOG_AVAILABLE:
        import structlog

        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.dev.ConsoleRenderer() if sys.stdout.isatty()
                else structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
            context_class=dict,
        )
    else:
        # structlog 没装时给标准 logging 加一个简单 handler
        root = logging.getLogger()
        if not root.handlers:
            handler = logging.StreamHandler(sys.stdout)
            fmt = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s %(message)s"
            )
            handler.setFormatter(fmt)
            root.addHandler(handler)
            root.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# 公共入口
# ---------------------------------------------------------------------------


def init_logging() -> None:
    """公开入口：提前触发 logging 配置（server lifespan 启动时调用）。

    不调用也没关系——get_logger 内部也会懒初始化。此函数只是为了让
    日志系统在 server 启动阶段就完成配置，避免最早几条日志格式不对。
    """
    _ensure_initialized()


def get_logger(name: str = "harness", **context: Any):
    """获取一个配置好的 logger。

    Args:
        name: logger 名字（structlog 下会自动注入）。
        **context: 附加固定上下文（如 session_id），会自动合并到每条日志。

    Returns:
        structlog bound logger 或标准 logging.Logger。
    """
    _ensure_initialized()

    if _STRUCTLOG_AVAILABLE:
        import structlog
        logger = structlog.get_logger(name=name)
        if context:
            logger = logger.bind(**context)
        return logger

    # 标准 logging 降级
    logger = logging.getLogger(name)
    return _StdLoggerWrapper(logger, context)


class _StdLoggerWrapper:
    """把标准 logging.Logger 包装成支持 ``.info(event, **kw)`` 形式。

    structlog 的 ``log.info("msg", key=val)`` 等价于
    标准 logging 的 ``log.info("msg key=val")``。
    """

    def __init__(self, logger: logging.Logger, context: dict[str, Any] | None = None) -> None:
        self._logger = logger
        self._context = context or {}

    def _format(self, event: str, **kw: Any) -> str:
        all_kw = {**self._context, **kw}
        if all_kw:
            kw_str = " ".join(f"{k}={v!r}" for k, v in all_kw.items())
            return f"{event} [{kw_str}]"
        return event

    def info(self, event: str, **kw: Any) -> None:  # noqa: D401 - 包装器
        self._logger.info(self._format(event, **kw))

    def warning(self, event: str, **kw: Any) -> None:  # noqa: D401
        self._logger.warning(self._format(event, **kw))

    def warn(self, event: str, **kw: Any) -> None:  # noqa: D401
        self.warning(event, **kw)

    def error(self, event: str, **kw: Any) -> None:  # noqa: D401
        self._logger.error(self._format(event, **kw))

    def debug(self, event: str, **kw: Any) -> None:  # noqa: D401
        self._logger.debug(self._format(event, **kw))

    def exception(self, event: str, **kw: Any) -> None:  # noqa: D401
        self._logger.exception(self._format(event, **kw))

    def bind(self, **kw: Any) -> "_StdLoggerWrapper":
        """返回一个合并了新上下文的新 wrapper。"""
        return _StdLoggerWrapper(self._logger, {**self._context, **kw})
