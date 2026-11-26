"""租户配额应用服务（W3-PLAT-01）。

在 run 前检查三类上限，超限统一抛 ``BizError(429)``：

    - 并发运行数：agent_runs 中 queued / running 的条数
    - 当日消息数：tenant_usage_daily.messages
    - 当日 token：tenant_usage_daily.tokens

用量按 UTC 自然日累加；没有配额记录时使用免费版默认值并落库，
方便管理端后续直接 PUT 修改。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from harness.platform.api.exceptions import BizError
from harness.platform.repository.agent_run_repository import AgentRunRepository
from harness.platform.repository.tenant_quota_repository import (
    TenantQuotaRepository,
    TenantUsageRepository,
)

log = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENT_RUNS = 4
DEFAULT_MAX_DAILY_MESSAGES = 2000
DEFAULT_MAX_DAILY_TOKENS = 2_000_000

_EDITABLE_FIELDS = (
    "max_concurrent_runs",
    "max_daily_messages",
    "max_daily_tokens",
)


def today_utc() -> str:
    """当前 UTC 日期（YYYY-MM-DD）。"""
    return datetime.now(timezone.utc).date().isoformat()


class QuotaService:
    """配额读取、检查与用量累加。"""

    def __init__(self, session) -> None:
        self.session = session
        self.quotas = TenantQuotaRepository(session)
        self.usage = TenantUsageRepository(session)
        self.runs = AgentRunRepository(session)

    async def get_quota(self, tenant_id: str):
        """取租户配额；不存在时创建默认免费版记录。"""
        quota = await self.quotas.get(tenant_id)
        if quota is not None:
            return quota

        from harness.platform.entity.tenant_quota import TenantQuota

        quota = TenantQuota(
            tenant_id=tenant_id,
            max_concurrent_runs=DEFAULT_MAX_CONCURRENT_RUNS,
            max_daily_messages=DEFAULT_MAX_DAILY_MESSAGES,
            max_daily_tokens=DEFAULT_MAX_DAILY_TOKENS,
        )
        return await self.quotas.save(quota)

    async def ensure_available(self, tenant_id: str) -> None:
        """run 前检查；超限抛 429。"""
        quota = await self.get_quota(tenant_id)
        date = today_utc()
        usage = await self.usage.get(tenant_id, date)
        active = await self.runs.count_active(tenant_id)

        if active >= quota.max_concurrent_runs:
            raise BizError(
                429,
                "并发运行数已达上限",
                detail=f"active={active} limit={quota.max_concurrent_runs}",
            )
        used_messages = usage.messages if usage is not None else 0
        used_tokens = usage.tokens if usage is not None else 0
        if used_messages >= quota.max_daily_messages:
            raise BizError(
                429,
                "今日消息数已达上限",
                detail=f"used={used_messages} limit={quota.max_daily_messages}",
            )
        if used_tokens >= quota.max_daily_tokens:
            raise BizError(
                429,
                "今日 token 用量已达上限",
                detail=f"used={used_tokens} limit={quota.max_daily_tokens}",
            )

    async def record_run_started(self, tenant_id: str) -> None:
        """记录一次运行开始（失败不影响主流程，由调用方兜底）。"""
        await self.usage.increment(tenant_id, today_utc(), runs=1)

    async def record_usage(
        self, tenant_id: str, *, messages: int = 0, tokens: int = 0
    ) -> None:
        """累加消息数与 token 用量。"""
        if messages <= 0 and tokens <= 0:
            return
        await self.usage.increment(
            tenant_id, today_utc(), messages=messages, tokens=tokens
        )

    async def summary(self, tenant_id: str) -> dict[str, Any]:
        """配额 + 当日用量 + 当前并发。"""
        quota = await self.get_quota(tenant_id)
        date = today_utc()
        usage = await self.usage.get(tenant_id, date)
        return {
            "tenant_id": tenant_id,
            "date": date,
            "quota": {
                "max_concurrent_runs": quota.max_concurrent_runs,
                "max_daily_messages": quota.max_daily_messages,
                "max_daily_tokens": quota.max_daily_tokens,
            },
            "usage": {
                "runs_started": usage.runs_started if usage else 0,
                "messages": usage.messages if usage else 0,
                "tokens": usage.tokens if usage else 0,
            },
            "active_runs": await self.runs.count_active(tenant_id),
            "updated_at": quota.updated_at.isoformat(),
        }

    async def update(self, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """更新配额（只接受白名单字段，未传字段保持不变）。"""
        quota = await self.get_quota(tenant_id)
        changed = False
        for field in _EDITABLE_FIELDS:
            value = payload.get(field)
            if value is None:
                continue
            if int(value) < 0:
                raise BizError(400, f"{field} 不能为负数")
            setattr(quota, field, int(value))
            changed = True
        if changed:
            quota.updated_at = datetime.now(timezone.utc)
            await self.quotas.save(quota)
        return await self.summary(tenant_id)


__all__ = [
    "DEFAULT_MAX_CONCURRENT_RUNS",
    "DEFAULT_MAX_DAILY_MESSAGES",
    "DEFAULT_MAX_DAILY_TOKENS",
    "QuotaService",
    "today_utc",
]
