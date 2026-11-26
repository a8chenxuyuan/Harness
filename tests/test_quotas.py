"""租户配额测试（W3-PLAT-01）。"""

from __future__ import annotations

import pytest

from harness.platform.api.exceptions import BizError
from harness.platform.entity.agent_run import AgentRun
from harness.platform.service.quota_service import QuotaService


async def test_default_quota_and_summary(db_session) -> None:
    """无记录时返回免费版默认值，并落库便于后续修改。"""
    service = QuotaService(db_session)
    summary = await service.summary("tenant-a")

    assert summary["quota"]["max_concurrent_runs"] == 4
    assert summary["usage"] == {"runs_started": 0, "messages": 0, "tokens": 0}
    assert summary["active_runs"] == 0

    updated = await service.update(
        "tenant-a", {"max_daily_messages": 10, "max_daily_tokens": 1000}
    )
    assert updated["quota"]["max_daily_messages"] == 10
    # 未传字段保持不变
    assert updated["quota"]["max_concurrent_runs"] == 4


async def test_daily_message_limit_raises_429(db_session) -> None:
    """当日消息数达到上限后禁止再跑。"""
    service = QuotaService(db_session)
    await service.update("tenant-b", {"max_daily_messages": 0})

    with pytest.raises(BizError) as exc:
        await service.ensure_available("tenant-b")
    assert exc.value.status_code == 429


async def test_concurrent_limit_counts_running_runs(db_session) -> None:
    """并发上限按 agent_runs 中 queued / running 实时统计。"""
    db_session.add(
        AgentRun(run_id="run-active", tenant_id="tenant-c", user_id="u", status="running")
    )
    await db_session.commit()

    service = QuotaService(db_session)
    await service.update("tenant-c", {"max_concurrent_runs": 1})

    with pytest.raises(BizError) as exc:
        await service.ensure_available("tenant-c")
    assert "并发" in exc.value.message


async def test_usage_increment(db_session) -> None:
    """消息与 token 按天累加。"""
    service = QuotaService(db_session)
    await service.record_run_started("tenant-d")
    await service.record_usage("tenant-d", messages=2, tokens=120)

    summary = await service.summary("tenant-d")
    assert summary["usage"] == {"runs_started": 1, "messages": 2, "tokens": 120}


async def test_quota_api_requires_owner(client, owner_headers, auth_headers) -> None:
    """PUT/GET 限 owner/admin；普通 member 403。"""
    forbidden = await client.get("/api/v1/tenant/quotas", headers=auth_headers)
    assert forbidden.status_code == 403

    updated = await client.put(
        "/api/v1/tenant/quotas",
        json={"max_daily_messages": 50},
        headers=owner_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["quota"]["max_daily_messages"] == 50

    fetched = await client.get("/api/v1/tenant/quotas", headers=owner_headers)
    assert fetched.status_code == 200
    assert fetched.json()["data"]["quota"]["max_daily_messages"] == 50
