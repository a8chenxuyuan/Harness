"""异步事件总线。

EventBus 是 harness 观测体系的中枢：Loop / ToolExecutor / ContextAssembler
把事件 publish 进来，日志、指标、tracing、前端 SSE 等消费方通过 subscribe
注册 handler。

设计要点：
- handler 全部是 async def；publish 用 create_task 调度，不阻塞调用方
- unsubscribe 支持 handler 函数本身作为 key
- 默认进程内单例（全局 get_event_bus()），也允许按需构造多实例
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .types import Event, EventType

log = logging.getLogger(__name__)

# 全局单例实例，懒加载
_global_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """返回进程内的全局 EventBus 单例。

    首次调用时构造；后续全模块共用同一个 bus。

    Returns:
        EventBus 实例。
    """
    global _global_bus
    if _global_bus is None:
        _global_bus = EventBus()
    return _global_bus


class EventBus:
    """异步事件总线。

    Attributes:
        _handlers: EventType → handler callable 列表。
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[Callable[[Event], Awaitable[Any]]]] = {}

    # --- 订阅 -----------------------------------------------------------------

    def subscribe(
        self,
        event_type: EventType,
        handler: Callable[[Event], Awaitable[Any]],
    ) -> None:
        """注册一个事件 handler。

        Args:
            event_type: 关心的事件类型。
            handler: async def handler(event) 形式的回调。
        """
        handlers = self._handlers.setdefault(event_type, [])
        if handler not in handlers:
            handlers.append(handler)

    def unsubscribe(
        self,
        event_type: EventType,
        handler: Callable[[Event], Awaitable[Any]],
    ) -> None:
        """取消注册。

        Args:
            event_type: 事件类型。
            handler: 要移除的 handler。
        """
        handlers = self._handlers.get(event_type)
        if handlers is None:
            return
        try:
            handlers.remove(handler)
        except ValueError:
            # 不在列表里就静默忽略
            pass

    # --- 发布 -----------------------------------------------------------------

    async def publish(self, event: Event) -> None:
        """发布一条事件。

        所有注册到 event.type 的 handler 会被并发调度；单个 handler
        抛异常只打日志，不影响其他 handler。

        Args:
            event: 事件实例。
        """
        handlers = self._handlers.get(event.type)
        if not handlers:
            return

        tasks: list[asyncio.Task[Any]] = []
        for handler in handlers:
            task = asyncio.create_task(self._safe_call(handler, event))
            tasks.append(task)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    async def _safe_call(
        handler: Callable[[Event], Awaitable[Any]],
        event: Event,
    ) -> None:
        """包装单次 handler 调用，吞掉异常防止一个坏掉的 handler 拖垮整个 bus。"""
        try:
            await handler(event)
        except Exception:  # noqa: BLE001 - 这里就是要 catch 所有 handler 异常
            log.exception(
                "EventBus handler %r 处理事件 %r 时抛异常",
                getattr(handler, "__name__", repr(handler)),
                event.type.value,
            )
