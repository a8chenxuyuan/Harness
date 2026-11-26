"""租户配额入参（W3-PLAT-01）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class QuotaUpdateRequest(BaseModel):
    """PUT /api/v1/tenant/quotas 请求体（字段可选，未传保持不变）。"""

    max_concurrent_runs: int | None = Field(default=None, ge=0, le=1000)
    max_daily_messages: int | None = Field(default=None, ge=0, le=10_000_000)
    max_daily_tokens: int | None = Field(default=None, ge=0, le=10_000_000_000)


__all__ = ["QuotaUpdateRequest"]
