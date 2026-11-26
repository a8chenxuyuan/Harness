"""API Key 管理接口入参（DTO）。

响应模型在 ``api.vo.api_key_vo``。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ApiKeyCreateRequest(BaseModel):
    """POST /api-keys 请求体 —— 签发一个新 API Key。

    明文 key 只在创建响应里出现一次，服务端不留副本。
    """

    name: str = Field(..., min_length=1, max_length=128, description="展示名称，如 ci-pipeline")
    expires_in_days: int | None = Field(
        default=None,
        ge=1,
        le=3650,
        description="有效期天数；不传=永不过期",
    )


__all__ = ["ApiKeyCreateRequest"]
