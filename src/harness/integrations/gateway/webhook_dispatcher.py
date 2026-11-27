"""WebhookDispatcher — 把 EventBus 事件转发给外部 Webhook 订阅（W4-CHAN-03）。

启动时订阅 EventBus 的全部事件类型；事件到达后按
租户（payload.tenant_id，缺失时不做租户过滤）与订阅的
event_types 过滤，对命中的订阅异步投递（带重试，见 webhook_service）。

投递在独立 task 中执行，失败只记 delivery 表，不影响主流程。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from harness.common.event.bus import EventBus, get_event_bus
from harness.common.event.types import Event, EventType

log = logging.getLogger(__name__)


class WebhookDispatcher:
    """EventBus → Webhook 投递调度器。

    Attributes:
        client: 可注入的 httpx.AsyncClient（测试用 MockTransport）；
            None 表示每次投递内部新建。
    """

    def __init__(self, *, client: Any = None) -> None:
        self.client = client
        self._handler = None
        self._types: list[EventType] = []

    def start(self, bus: EventBus | None = None) -> None:
        """订阅全部事件类型（重复 start 无副作用）。"""
        if self._handler is not None:
            return
        bus = bus or get_event_bus()
        self._handler = self._on_event
        for et in EventType:
            bus.subscribe(et, self._handler)
            self._types.append(et)
        log.info("webhook dispatcher: 已订阅 %d 类事件", len(self._types))

    def stop(self) -> None:
        """取消全部订阅（lifespan shutdown 调用）。"""
        if self._handler is None:
            return
        bus = get_event_bus()
        for et in self._types:
            bus.unsubscribe(et, self._handler)
        self._types = []
        self._handler = None

    async def _on_event(self, event: Event) -> None:
        """EventBus handler：快速返回，投递放到独立 task。"""
        asyncio.create_task(self._dispatch(event))

    async def _dispatch(self, event: Event) -> None:
        """单条事件的完整投递流程：查启用订阅 → 过滤 → 逐个投递。"""
        from harness.platform.infra.engine import get_session_factory
        from harness.platform.repository.webhook_repository import WebhookRepository
        from harness.platform.service import webhook_service

        factory = get_session_factory()
        async with factory() as session:
            subs = await WebhookRepository(session).list_active_subscriptions()

            # 租户过滤：事件 payload 带 tenant_id 才过滤；缺失时投给全部启用订阅
            tenant_id = event.payload.get("tenant_id")
            if tenant_id:
                subs = [s for s in subs if s.tenant_id == tenant_id]

            event_type = event.type.value
            for sub in subs:
                if not webhook_service._matches(sub, event_type):
                    continue
                try:
                    await webhook_service.run_delivery(
                        session,
                        sub,
                        event_type,
                        event.to_dict(),
                        client=self.client,
                    )
                except Exception:  # noqa: BLE001 — 单个订阅失败不影响其他
                    log.exception(
                        "webhook 投递失败: subscription=%s event=%s",
                        sub.id,
                        event_type,
                    )


__all__ = ["WebhookDispatcher"]
