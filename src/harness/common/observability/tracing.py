"""OpenTelemetry Tracing 封装。

opentelemetry 是可选依赖——没装时本模块返回的是 no-op 实现，
不会让主流程 import 失败。检测逻辑在 _is_otel_available()。
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

log = logging.getLogger(__name__)


def _is_otel_available() -> bool:
    """检测 opentelemetry-api 是否可用。"""
    try:
        import opentelemetry  # noqa: F401
        return True
    except ImportError:
        return False


_OTEL_AVAILABLE = _is_otel_available()


# ---------------------------------------------------------------------------
# no-op 实现
# ---------------------------------------------------------------------------


class _NoopSpan:
    """当 opentelemetry 没装时的占位 span。"""

    def set_attribute(self, key: str, value: Any) -> None:  # noqa: D401 - no-op 无需 doc
        pass

    def record_exception(self, exc: BaseException) -> None:  # noqa: D401 - no-op
        pass

    def end(self) -> None:  # noqa: D401 - no-op
        pass


@contextmanager
def _noop_span_context(name: str, attrs: dict[str, Any] | None = None) -> Iterator[_NoopSpan]:
    """opentelemetry 不可用时的 context manager。"""
    span = _NoopSpan()
    if attrs:
        for k, v in attrs.items():
            span.set_attribute(k, v)
    yield span
    span.end()


# ---------------------------------------------------------------------------
# OTel 真实现
# ---------------------------------------------------------------------------


def _make_otel_context_manager():
    """构造真正的 OTel context manager（仅当 OTel 可用时被调用一次）。"""
    from opentelemetry import trace

    @contextmanager
    def _otel_context(name: str, attrs: dict[str, Any] | None = None) -> Iterator[Any]:
        tracer = trace.get_tracer("harness")
        with tracer.start_as_current_span(name, attributes=attrs or {}) as span:
            yield span

    return _otel_context


# ---------------------------------------------------------------------------
# 公共入口
# ---------------------------------------------------------------------------

if _OTEL_AVAILABLE:
    _context_manager_impl = _make_otel_context_manager()
else:
    _context_manager_impl = _noop_span_context


def start_span(name: str, attrs: dict[str, Any] | None = None):
    """启动一个 tracing span，返回 context manager。

    用法::

        with start_span("model.generate", {"session_id": sess}) as span:
            ...
            span.set_attribute("tokens", 123)

    opentelemetry 没装时是 no-op，不会抛异常。

    Args:
        name: span 名称，按点分层级（如 "model.generate"）。
        attrs: 初始属性字典，可选。

    Returns:
        context manager，yield span 对象。
    """
    return _context_manager_impl(name, attrs)


def end_span(span: Any, attrs: dict[str, Any] | None = None) -> None:
    """结束一个 span 并（可选）追加属性。

    Args:
        span: start_span 返回的 span 对象。
        attrs: 追加属性字典，可选。
    """
    if attrs is not None and span is not None:
        for k, v in attrs.items():
            try:
                span.set_attribute(k, v)
            except Exception:  # noqa: BLE001
                pass
    if span is not None:
        try:
            span.end()
        except Exception:  # noqa: BLE001
            pass


def init_otel(service_name: str = "harness") -> None:
    """可选：初始化全局 OTel provider。

    没装 opentelemetry 时静默跳过，只打 debug 日志。

    Args:
        service_name: 服务名，写入 Resource 属性。
    """
    if not _OTEL_AVAILABLE:
        log.debug("opentelemetry 未安装，跳过 init_otel")
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)
        log.info("opentelemetry 已初始化，service.name=%s", service_name)
    except Exception:  # noqa: BLE001
        log.exception("init_otel 失败")
