"""Webhook 管理接口出参（VO）。

请求模型在 ``api.dto.webhook_dto``。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WebhookItem(BaseModel):
    """单个 Webhook 订阅的展示项（列表/创建响应共用）。

    secret 只露出前 8 位前缀；完整密钥仅在创建响应返回一次。
    """

    id: str = Field(..., description="订阅 ID")
    name: str = Field(..., description="展示名称")
    url: str = Field(..., description="回调 URL")
    secret_prefix: str = Field(..., description="签名密钥前 8 位（供人工辨认）")
    event_types: list[str] = Field(default_factory=list, description="关心的事件类型；空 = 全部")
    is_active: bool = Field(default=True, description="是否启用")
    created_by: str = Field(..., description="创建人用户 ID")
    created_at: str | None = Field(default=None, description="创建时间（UTC ISO）")
    updated_at: str | None = Field(default=None, description="更新时间（UTC ISO）")


class WebhookCreateResponse(BaseModel):
    """POST /webhooks 响应体 —— 新建的订阅 + 明文密钥（仅此一次）。"""

    webhook: WebhookItem = Field(..., description="订阅记录（脱敏）")
    secret: str = Field(..., description="签名密钥明文；只在本次响应出现，请立即保存")


class WebhookListResponse(BaseModel):
    """GET /webhooks 响应体 —— 租户下全部订阅（按创建时间倒序）。"""

    items: list[WebhookItem] = Field(default_factory=list, description="订阅列表")
    total: int = Field(default=0, description="总数")


class WebhookDeleteResponse(BaseModel):
    """DELETE /webhooks/{id} 响应体 —— 删除结果。"""

    deleted: bool = Field(default=True, description="true=已删除（含投递记录）")


class DeliveryItem(BaseModel):
    """单条投递记录。"""

    id: str = Field(..., description="投递记录 ID")
    subscription_id: str = Field(..., description="所属订阅 ID")
    event_type: str = Field(..., description="事件类型")
    status: str = Field(..., description="最终状态：success | failed")
    status_code: int | None = Field(default=None, description="最后一次 HTTP 状态码；网络异常为空")
    attempts: int = Field(default=0, description="总尝试次数")
    duration_ms: int | None = Field(default=None, description="总耗时（毫秒）")
    response_body: str = Field(default="", description="最后一次响应体或异常信息（截断）")
    created_at: str | None = Field(default=None, description="创建时间（UTC ISO）")


class DeliveryListResponse(BaseModel):
    """GET /webhooks/{id}/deliveries 响应体 —— 投递记录（最新在前）。"""

    items: list[DeliveryItem] = Field(default_factory=list, description="投递记录列表")
    total: int = Field(default=0, description="总数")


class WebhookTestResponse(BaseModel):
    """POST /webhooks/{id}/test 响应体 —— 测试事件投递结果。"""

    delivery: DeliveryItem = Field(..., description="本次测试的投递记录")


__all__ = [
    "WebhookItem",
    "WebhookCreateResponse",
    "WebhookListResponse",
    "WebhookDeleteResponse",
    "DeliveryItem",
    "DeliveryListResponse",
    "WebhookTestResponse",
]
