"""Webhook 管理接口入参（DTO）。

响应模型在 ``api.vo.webhook_vo``。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WebhookCreateRequest(BaseModel):
    """POST /webhooks 请求体 —— 登记一个新 Webhook 订阅。"""

    name: str = Field(..., min_length=1, max_length=128, description="展示名称，如 ops-alert")
    url: str = Field(..., min_length=1, max_length=512, description="回调 URL（仅 http/https）")
    event_types: list[str] | None = Field(
        default=None,
        max_length=64,
        description="关心的事件类型列表（EventType.value）；不传或空 = 全部事件",
    )


__all__ = ["WebhookCreateRequest"]
