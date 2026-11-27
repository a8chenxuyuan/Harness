"""Webhook 实体 — 事件推送订阅与投递记录（W4-CHAN-03）。

两张表：
    - webhook_subscriptions：外部订阅方登记（URL + HMAC 签名密钥 + 关心的事件类型）
    - webhook_deliveries：每次事件投递的最终结果（成功/失败、重试次数、耗时）

密钥说明：secret 以明文落库 —— 投递时服务端要用它计算 HMAC-SHA256 签名，
哈希存储无法完成签名；明文仅在创建响应里返回一次，列表只展示前 8 位前缀。
"""

from __future__ import annotations

from datetime import datetime, timezone

try:
    from sqlmodel import Field, SQLModel  # type: ignore
    from sqlalchemy import Column, Text  # type: ignore
except Exception:  # noqa: BLE001
    class Field:  # type: ignore[no-redef]
        def __init__(self, *a, **kw): ...

    class SQLModel:  # type: ignore[no-redef]
        def __init_subclass__(cls, **kw): ...


class WebhookSubscription(SQLModel, table=True):  # noqa: F811
    """Webhook 订阅记录。"""

    __tablename__ = "webhook_subscriptions"

    id: str = Field(primary_key=True, max_length=36)
    tenant_id: str = Field(index=True, max_length=36)
    name: str = Field(max_length=128)
    url: str = Field(max_length=512)
    # HMAC-SHA256 签名密钥（服务端留存用于签名，不外传）
    secret: str = Field(max_length=128)
    # JSON 数组字符串：关心的事件类型（EventType.value）；"[]" = 全部事件
    event_types: str = Field(default="[]", max_length=2048)
    is_active: bool = Field(default=True)
    created_by: str = Field(max_length=36)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WebhookDelivery(SQLModel, table=True):  # noqa: F811
    """Webhook 投递记录（一次事件对一条订阅的最终结果，含全部重试）。"""

    __tablename__ = "webhook_deliveries"

    id: str = Field(primary_key=True, max_length=36)
    subscription_id: str = Field(index=True, max_length=36)
    event_type: str = Field(max_length=64)
    # success | failed（2xx 即 success，其余含网络异常都算 failed）
    status: str = Field(max_length=16)
    status_code: int | None = Field(default=None)
    attempts: int = Field(default=0)
    duration_ms: int | None = Field(default=None)
    request_body: str = Field(default="", sa_column=Column(Text))
    response_body: str = Field(default="", sa_column=Column(Text))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), index=True
    )
