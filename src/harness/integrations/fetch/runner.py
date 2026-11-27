"""数据拉取编排器（W4.1-CHAN-06）。

按用户的渠道绑定逐源拉取 → 入库（幂等）→ 新数据发 EventBus（PLATFORM_ITEM
事件，webhook 订阅者与摘要系统都可消费）→ 更新增量游标。单源失败不阻塞
其他源，错误记录在 fetch_state。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from harness.common.event.bus import get_event_bus
from harness.common.event.types import Event, EventType
from harness.integrations.fetch.base import FetchError, FetchedItem
from harness.integrations.fetch.wecom_sources import get_fetchers
from harness.platform.entity.platform_item import PlatformItem
from harness.platform.repository.platform_item_repository import PlatformItemRepository

log = logging.getLogger(__name__)


async def _item_to_entity(
    item: FetchedItem,
    *,
    tenant_id: str,
    user_id: str,
    binding_id: str,
    platform: str,
    source: str,
) -> PlatformItem:
    return PlatformItem(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        binding_id=binding_id,
        platform=platform,
        source=source,
        item_type=item.item_type,
        external_id=item.external_id,
        title=item.title[:256],
        summary=item.summary[:1024],
        raw=json.dumps(item.raw, ensure_ascii=False)[:8192],
        occurred_at=item.occurred_at,
    )


async def run_fetch_for_user(
    session: Any,
    bindings: list[Any],
    adapters: dict[str, Any],
) -> dict[str, Any]:
    """对一个用户的全部绑定执行拉取。

    Args:
        session: AsyncSession。
        bindings: 该用户的 active channel_binding 记录列表。
        adapters: platform → 渠道 adapter（如 {"wecom": adapter}）；
                  缺对应 adapter 的平台跳过。

    Returns:
        {"sources": [{"platform","source","fetched","new","error"}], "new_total"}
    """
    repo = PlatformItemRepository(session)
    bus = get_event_bus()
    report: list[dict[str, Any]] = []
    new_total = 0

    for binding in bindings:
        platform = binding.platform
        adapter = adapters.get(platform)
        if adapter is None:
            continue
        for fetcher in get_fetchers(platform, adapter):
            state = await repo.get_state(binding.id, fetcher.source)
            cursor = state.cursor if state else ""
            entry: dict[str, Any] = {
                "platform": platform,
                "source": fetcher.source,
                "fetched": 0,
                "new": 0,
                "error": "",
            }
            try:
                items, new_cursor = await fetcher.fetch(binding, cursor)
                entry["fetched"] = len(items)
                for item in items:
                    entity = await _item_to_entity(
                        item,
                        tenant_id=binding.tenant_id,
                        user_id=binding.harness_user_id,
                        binding_id=binding.id,
                        platform=platform,
                        source=fetcher.source,
                    )
                    created = await repo.upsert(entity)
                    entry["new"] += 1 if created else 0
                    if created:
                        await bus.publish(
                            Event(
                                type=EventType.PLATFORM_ITEM,
                                session_id=f"fetch:{binding.id}",
                                payload={
                                    "tenant_id": binding.tenant_id,
                                    "user_id": binding.harness_user_id,
                                    "platform": platform,
                                    "source": fetcher.source,
                                    "item_type": item.item_type,
                                    "external_id": item.external_id,
                                    "title": item.title,
                                    "summary": item.summary,
                                    "occurred_at": item.occurred_at.isoformat(),
                                },
                            )
                        )
                await repo.set_state(binding.id, fetcher.source, cursor=new_cursor)
            except FetchError as exc:
                entry["error"] = str(exc)
                await repo.set_state(binding.id, fetcher.source, error=str(exc)[:512])
                log.warning("fetch[%s/%s] 失败: %s", platform, fetcher.source, exc)
            report.append(entry)
            new_total += entry["new"]

    return {"sources": report, "new_total": new_total}


__all__ = ["run_fetch_for_user"]
