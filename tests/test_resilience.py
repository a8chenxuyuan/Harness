"""模型韧性测试（W3-KERN-03）。

覆盖：
    - 首块输出前失败可重试（指数退避可关闭便于测试）
    - 已经输出内容后失败不重试，避免重复文本
    - 连续失败触发熔断，熔断期内快速失败
    - 分块等待超时
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from harness.common.message.msg import Msg
from harness.core.model.base import Model
from harness.core.model.resilient import (
    CircuitBreaker,
    ModelUnavailableError,
    ResilientModel,
)
from harness.core.model.types import ChatChunk, GenerateOptions


class _FlakyModel(Model):
    """前 N 次调用直接失败，之后正常输出。"""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0
        super().__init__()

    async def stream(
        self,
        messages: list[Msg],
        tools: list[dict[str, Any]],
        options: GenerateOptions,
    ):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("上游不可用")
        yield ChatChunk(delta="ok")


class _MidFailModel(Model):
    """先输出一块再失败。"""

    def __init__(self) -> None:
        self.calls = 0
        super().__init__()

    async def stream(
        self,
        messages: list[Msg],
        tools: list[dict[str, Any]],
        options: GenerateOptions,
    ):
        self.calls += 1
        yield ChatChunk(delta="已输出")
        raise RuntimeError("流中断")


class _SlowModel(Model):
    """每次取块都睡很久，用于触发超时。"""

    async def stream(
        self,
        messages: list[Msg],
        tools: list[dict[str, Any]],
        options: GenerateOptions,
    ):
        await asyncio.sleep(1.0)
        yield ChatChunk(delta="迟到")


async def _collect(model: Model) -> list[str]:
    return [
        chunk.delta
        async for chunk in model.stream([], [], GenerateOptions())
    ]


async def test_retry_before_first_chunk() -> None:
    """前两次失败、第三次成功，调用方只看到最后一份结果。"""
    inner = _FlakyModel(failures=2)
    wrapped = ResilientModel(
        inner, retries=2, backoff=0, breaker=CircuitBreaker()
    )

    assert await _collect(wrapped) == ["ok"]
    assert inner.calls == 3


async def test_no_retry_after_content_emitted() -> None:
    """已经 yield 过内容后失败不允许重试。"""
    inner = _MidFailModel()
    wrapped = ResilientModel(
        inner, retries=3, backoff=0, breaker=CircuitBreaker()
    )

    with pytest.raises(RuntimeError, match="流中断"):
        await _collect(wrapped)
    assert inner.calls == 1


async def test_circuit_breaker_opens_and_fast_fails() -> None:
    """连续失败达到阈值后，后续调用不再触达底层模型。"""
    inner = _FlakyModel(failures=99)
    wrapped = ResilientModel(
        inner,
        retries=0,
        backoff=0,
        breaker=CircuitBreaker(),
        circuit_threshold=2,
        circuit_cooldown=60,
    )

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await _collect(wrapped)

    with pytest.raises(ModelUnavailableError):
        await _collect(wrapped)
    assert inner.calls == 2


def test_circuit_breaker_half_open_after_cooldown() -> None:
    """冷却到期后放行一次探测。"""
    now = [0.0]
    breaker = CircuitBreaker(clock=lambda: now[0])

    assert breaker.allow("m", cooldown=10) is True
    assert breaker.record_failure("m", threshold=1, cooldown=10) is True
    assert breaker.allow("m", cooldown=10) is False

    now[0] = 11.0
    assert breaker.allow("m", cooldown=10) is True


async def test_timeout_aborts_slow_chunk() -> None:
    """单块等待超时即中断。"""
    wrapped = ResilientModel(
        _SlowModel(), timeout=0.01, retries=0, backoff=0, breaker=CircuitBreaker()
    )

    with pytest.raises(TimeoutError):
        await _collect(wrapped)
