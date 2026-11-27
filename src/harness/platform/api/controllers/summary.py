"""今日摘要与手动拉取接口（W4.1-CHAN-06）。

接口清单：
    GET  /summary/today   当前用户今日摘要（数据超过 TTL 时惰性触发拉取）
    POST /fetch/run       手动触发当前用户拉取（owner/admin，联调验证用）
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from harness.platform.api.deps import get_current_user, get_db, require_role
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse
from harness.platform.repository.channel_binding_repository import ChannelBindingRepository
from harness.platform.repository.platform_item_repository import PlatformItemRepository
from harness.integrations.fetch.runner import run_fetch_for_user

log = logging.getLogger(__name__)

router = APIRouter(prefix="/summary", tags=["summary"])

# 惰性拉取 TTL：数据比这更旧就先拉再聚合
FETCH_TTL_SECONDS = 30 * 60


def _today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime.combine(now.date(), time.min, tzinfo=timezone.utc)


def _app_adapters(request: Request) -> dict:
    """从 app.state 取各渠道 adapter（wecom 等）。"""
    adapters: dict = {}
    if hasattr(request.app.state, "wecom_adapter"):
        adapters["wecom"] = request.app.state.wecom_adapter
    return adapters


async def _bindings_for_user(db: AsyncSession, user_id: str) -> list:
    repo = ChannelBindingRepository(db)
    return [b for b in await repo.list_for_user(user_id) if b.status == "active"]


@router.post("/run", response_model=ApiResponse[dict])
async def trigger_fetch(
    request: Request,
    admin: UserInfo = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动触发当前用户的平台数据拉取（联调验证用）。"""
    bindings = await _bindings_for_user(db, admin.user_id)
    report = await run_fetch_for_user(db, bindings, _app_adapters(request))
    return {"code": 0, "message": "ok", "data": report}


@router.get("/today", response_model=ApiResponse[dict])
async def today_summary(
    request: Request,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """当前用户今日摘要：各源计数 + 最近数据列表。

    数据过期（任一源超过 TTL 未同步）且对应 adapter 可用时，
    先同步一次再聚合；拉取失败不阻塞摘要返回。
    """
    adapters = _app_adapters(request)
    bindings = await _bindings_for_user(db, user.user_id)
    if bindings and adapters:
        await _lazy_fetch(db, bindings, adapters)

    repo = PlatformItemRepository(db)
    since = _today_start()
    items = await repo.list_today(user.user_id, since)
    counts = await repo.count_by_source(user.user_id, since)

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "date": since.date().isoformat(),
            "counts": counts,
            "total": len(items),
            "items": [
                {
                    "platform": i.platform,
                    "source": i.source,
                    "item_type": i.item_type,
                    "title": i.title,
                    "summary": i.summary,
                    "occurred_at": i.occurred_at.isoformat(),
                }
                for i in items[:10]
            ],
        },
    }


async def _lazy_fetch(db: AsyncSession, bindings: list, adapters: dict) -> None:
    """任一绑定有源超过 TTL 未同步 → 整体拉一次（失败只打日志）。"""
    from datetime import timedelta

    from harness.platform.repository.platform_item_repository import PlatformItemRepository

    repo = PlatformItemRepository(db)
    threshold = datetime.now(timezone.utc) - timedelta(seconds=FETCH_TTL_SECONDS)
    stale = False
    for binding in bindings:
        for state in [await repo.get_state(binding.id, s) for s in ("profile", "approval")]:
            if state is None or state.last_synced_at is None or state.last_synced_at < threshold:
                stale = True
                break
        if stale:
            break
    if not stale:
        return
    try:
        report = await run_fetch_for_user(db, bindings, adapters)
        log.info("lazy fetch: new=%s", report.get("new_total"))
    except Exception as exc:  # noqa: BLE001 摘要不因拉取失败而 500
        log.warning("lazy fetch 失败（忽略）: %s", exc)


__all__ = ["router"]
