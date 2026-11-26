"""OpenTelemetry Tracing 封装。

opentelemetry 是可选依赖——没装时本模块返回的是 no-op 实现，
不会让主流程 import 失败。检测逻辑在 _is_otel_available()。
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

from .context import current_span_attributes

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

    自动附带 ``request_id`` 与当前运行上下文（tenant_id / session_id /
    run_id 等），调用方只传业务专属属性即可。

    用法::

        with start_span("model.generate", {"model": name}) as span:
            ...
            span.set_attribute("tokens", 123)

    opentelemetry 没装时是 no-op，不会抛异常。

    Args:
        name: span 名称，按点分层级（如 "model.generate"）。
        attrs: 初始属性字典，可选。

    Returns:
        context manager，yield span 对象。
    """
    merged = current_span_attributes()
    if attrs:
        merged.update(attrs)
    return _context_manager_impl(name, merged)


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


_provider: Any = None


def init_otel(
    service_name: str = "harness",
    *,
    endpoint: str | None = None,
    exporter: Any = None,
) -> None:
    """初始化全局 OTel provider。

    - ``exporter`` 显式传入时直接使用（测试用 InMemorySpanExporter）
    - 否则读取 ``endpoint`` / ``OTEL_EXPORTER_OTLP_ENDPOINT`` / ``Settings.otlp_endpoint``，
      非空时挂 OTLP HTTP 批量导出
    - 都没有时仅注册 provider（span 创建但不外发），保证本地零配置可跑

    sdk 未安装时静默跳过。
    """
    global _provider
    if not _OTEL_AVAILABLE or _provider is not None:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

        provider = TracerProvider(
            resource=Resource.create({"service.name": service_name})
        )
        if exporter is not None:
            provider.add_span_processor(SimpleSpanProcessor(exporter))
        else:
            target = endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
            if not target:
                try:
                    from harness.common.config.settings import Settings

                    target = getattr(Settings(), "otlp_endpoint", "") or ""
                except Exception:  # noqa: BLE001
                    target = ""
            if target:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )

                provider.add_span_processor(
                    BatchSpanProcessor(OTLPSpanExporter(endpoint=target))
                )
                log.info("opentelemetry OTLP exporter: %s", target)

        trace.set_tracer_provider(provider)
        _provider = provider
        log.info("opentelemetry 已初始化，service.name=%s", service_name)
    except Exception:  # noqa: BLE001
        log.exception("init_otel 失败")


def get_tracer_provider() -> Any:
    """返回已初始化的 provider（测试 / 诊断用）。"""
    return _provider
