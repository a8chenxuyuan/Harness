"""模型调用韧性包装（W3-KERN-03）。

在任意 :class:`Model` 外包一层，提供：

1. **超时**：逐块等待超过 ``timeout`` 秒即中断（含首块等待）。
2. **重试**：仅在**首块产出之前**失败时重试，按指数退避；
   一旦向调用方 yield 过内容，中途失败不再重试，避免重复输出。
3. **熔断**：同一模型的连续失败达到阈值后打开，冷却期内直接快速失败；
   冷却结束进入半开，放行一次探测，成功即恢复。
4. **指标**：重试与熔断打开写入 ``harness_model_*_total``。

设计取舍：熔断状态是进程内共享的（按模型名分组），这样每次请求新建
模型实例也能共用同一份健康状态；多实例部署时各进程独立计数。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from harness.common.message.msg import Msg
from harness.common.observability.metrics import (
    record_model_circuit_open,
    record_model_retry,
)
from harness.core.model.base import Model
from harness.core.model.types import ChatChunk, GenerateOptions

log = logging.getLogger(__name__)


class ModelUnavailableError(RuntimeError):
    """模型处于熔断期，快速失败。"""


@dataclass
class _CircuitState:
    """单个模型的熔断状态。"""

    failures: int = 0
    opened_until: float | None = None


@dataclass
class CircuitBreaker:
    """进程内熔断器（按 key 维护失败计数）。

    Attributes:
        clock: 可注入时钟（测试用），默认 ``time.monotonic``。
    """

    clock: Any = field(default=time.monotonic)
    _states: dict[str, _CircuitState] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def allow(self, key: str, cooldown: float) -> bool:
        """是否允许一次调用；冷却到期自动转入半开放行。"""
        with self._lock:
            state = self._states.setdefault(key, _CircuitState())
            if state.opened_until is None:
                return True
            if self.clock() >= state.opened_until:
                # 冷却结束：半开，放行一次探测
                state.opened_until = None
                state.failures = 0
                return True
            return False

    def record_success(self, key: str) -> None:
        """成功一次：清零失败计数并关闭熔断。"""
        with self._lock:
            state = self._states.setdefault(key, _CircuitState())
            state.failures = 0
            state.opened_until = None

    def record_failure(self, key: str, threshold: int, cooldown: float) -> bool:
        """记录一次失败；达到阈值时打开熔断并返回 True。"""
        with self._lock:
            state = self._states.setdefault(key, _CircuitState())
            if state.opened_until is not None:
                return False
            state.failures += 1
            if state.failures >= max(1, threshold):
                state.opened_until = self.clock() + max(0.0, cooldown)
                return True
            return False

    def reset(self) -> None:
        """清空全部熔断状态（测试 / 运维手动恢复）。"""
        with self._lock:
            self._states.clear()


_default_breaker = CircuitBreaker()


def get_default_breaker() -> CircuitBreaker:
    """获取进程级共享熔断器。"""
    return _default_breaker


class ResilientModel(Model):
    """给底层模型加超时、重试与熔断。"""

    def __init__(
        self,
        inner: Model,
        *,
        timeout: float = 60.0,
        retries: int = 2,
        backoff: float = 0.5,
        circuit_threshold: int = 5,
        circuit_cooldown: float = 30.0,
        breaker: CircuitBreaker | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(capabilities=inner.capabilities)
        self.inner = inner
        self.timeout = timeout
        self.retries = max(0, retries)
        self.backoff = max(0.0, backoff)
        self.circuit_threshold = max(1, circuit_threshold)
        self.circuit_cooldown = max(0.0, circuit_cooldown)
        self.breaker = breaker or get_default_breaker()
        self.name = name or _model_key(inner)

    async def stream(
        self,
        messages: list[Msg],
        tools: list[dict[str, Any]],
        options: GenerateOptions,
    ) -> AsyncIterator[ChatChunk]:
        """带韧性策略的流式调用（契约同 ``Model.stream``）。"""
        if not self.breaker.allow(self.name, self.circuit_cooldown):
            record_model_circuit_open(self.name)
            raise ModelUnavailableError(
                f"模型 {self.name} 处于熔断冷却期，请稍后重试"
            )

        attempt = 0
        while True:
            emitted = False
            try:
                async for chunk in self._iterate(messages, tools, options):
                    emitted = True
                    yield chunk
                self.breaker.record_success(self.name)
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — 统一转重试/熔断
                opened = self.breaker.record_failure(
                    self.name, self.circuit_threshold, self.circuit_cooldown
                )
                if opened:
                    record_model_circuit_open(self.name)
                    log.warning("model: %s 连续失败触发熔断", self.name)

                if emitted or attempt >= self.retries:
                    raise

                attempt += 1
                reason = "timeout" if isinstance(exc, TimeoutError) else "error"
                record_model_retry(self.name, reason)
                log.warning(
                    "model: %s 第 %s 次重试（reason=%s err=%s）",
                    self.name,
                    attempt,
                    reason,
                    exc,
                )
                if self.backoff > 0:
                    await asyncio.sleep(self.backoff * (2 ** (attempt - 1)))
                if not self.breaker.allow(self.name, self.circuit_cooldown):
                    raise ModelUnavailableError(
                        f"模型 {self.name} 处于熔断冷却期，请稍后重试"
                    ) from exc

    async def _iterate(
        self,
        messages: list[Msg],
        tools: list[dict[str, Any]],
        options: GenerateOptions,
    ) -> AsyncIterator[ChatChunk]:
        """逐块等待底层流；单块超时即抛 TimeoutError。"""
        iterator = self.inner.stream(messages, tools, options).__aiter__()
        while True:
            try:
                chunk = await asyncio.wait_for(
                    iterator.__anext__(), timeout=self.timeout
                )
            except StopAsyncIteration:
                return
            yield chunk


def _model_key(model: Model) -> str:
    """生成熔断 key（类名 + 模型名），避免不同模型共享计数。"""
    return f"{type(model).__name__}:{getattr(model, 'model_name', '') or '-'}"


__all__ = [
    "CircuitBreaker",
    "ModelUnavailableError",
    "ResilientModel",
    "get_default_breaker",
]
