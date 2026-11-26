"""租户配额仓储（W3-PLAT-01）。"""

from __future__ import annotations


class TenantQuotaRepository:
    """tenant_quotas 读写。"""

    def __init__(self, session) -> None:
        self.session = session

    async def get(self, tenant_id: str):
        from harness.platform.entity.tenant_quota import TenantQuota

        return await self.session.get(TenantQuota, tenant_id)

    async def save(self, quota):
        self.session.add(quota)
        await self.session.commit()
        return quota


class TenantUsageRepository:
    """tenant_usage_daily 读写（按天累加）。"""

    def __init__(self, session) -> None:
        self.session = session

    async def get(self, tenant_id: str, usage_date: str):
        from harness.platform.entity.tenant_quota import TenantUsageDaily

        return await self.session.get(TenantUsageDaily, (tenant_id, usage_date))

    async def get_or_create(self, tenant_id: str, usage_date: str):
        from harness.platform.entity.tenant_quota import TenantUsageDaily

        usage = await self.get(tenant_id, usage_date)
        if usage is None:
            usage = TenantUsageDaily(tenant_id=tenant_id, usage_date=usage_date)
            self.session.add(usage)
            await self.session.commit()
        return usage

    async def increment(
        self,
        tenant_id: str,
        usage_date: str,
        *,
        runs: int = 0,
        messages: int = 0,
        tokens: int = 0,
    ):
        from datetime import datetime, timezone

        usage = await self.get_or_create(tenant_id, usage_date)
        usage.runs_started += max(0, runs)
        usage.messages += max(0, messages)
        usage.tokens += max(0, tokens)
        usage.updated_at = datetime.now(timezone.utc)
        self.session.add(usage)
        await self.session.commit()
        return usage
