"""Webhook 管理接口（W4-CHAN-03）。

对外暴露 Webhook 订阅的登记、查询、删除、投递记录查询与测试投递。
事件推送侧由 webhook_dispatcher 订阅 EventBus 自动完成，无需手动触发。

接口清单：
    POST   /webhooks                    登记新订阅（密钥明文仅此一次返回）
    GET    /webhooks                    列出租户下全部订阅（脱敏）
    DELETE /webhooks/{id}               删除订阅及其投递记录
    GET    /webhooks/{id}/deliveries    查询投递记录（最新在前）
    POST   /webhooks/{id}/test          发一条测试事件并返回投递结果
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from harness.platform.api.deps import get_current_user, get_db
from harness.platform.api.dto.webhook_dto import WebhookCreateRequest
from harness.platform.api.exceptions import BizError
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse
from harness.platform.api.vo.webhook_vo import (
    DeliveryItem,
    DeliveryListResponse,
    WebhookCreateResponse,
    WebhookDeleteResponse,
    WebhookItem,
    WebhookListResponse,
    WebhookTestResponse,
)
from harness.platform.service import webhook_service

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("", response_model=ApiResponse[WebhookCreateResponse])
async def create_webhook(
    body: WebhookCreateRequest,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """登记一个新 Webhook 订阅。

    签名密钥只在本次响应里出现一次，前端需提示用户立即保存；
    丢失只能删除订阅重建。
    """
    result = await webhook_service.create_webhook(
        db,
        user=user,
        name=body.name,
        url=body.url,
        event_types=body.event_types,
    )
    return {
        "code": 0,
        "message": "ok",
        "data": WebhookCreateResponse(
            webhook=WebhookItem(**result["webhook"]),
            secret=result["secret"],
        ),
    }


@router.get("", response_model=ApiResponse[WebhookListResponse])
async def list_webhooks(
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出租户下全部 Webhook 订阅（secret 只露前缀）。"""
    items = await webhook_service.list_webhooks(db, user)
    return {
        "code": 0,
        "message": "ok",
        "data": WebhookListResponse(
            items=[WebhookItem(**i) for i in items],
            total=len(items),
        ),
    }


@router.delete("/{webhook_id}", response_model=ApiResponse[WebhookDeleteResponse])
async def delete_webhook(
    webhook_id: str,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除一个订阅（同租户校验，连同其投递记录）。

    - 不存在 → BizError(404)
    - 跨租户 → BizError(403)
    """
    deleted = await webhook_service.delete_webhook(db, user, webhook_id)
    if not deleted:
        raise BizError(status.HTTP_404_NOT_FOUND, f"webhook {webhook_id} not found")
    return {
        "code": 0,
        "message": "ok",
        "data": WebhookDeleteResponse(deleted=True),
    }


@router.get("/{webhook_id}/deliveries", response_model=ApiResponse[DeliveryListResponse])
async def list_deliveries(
    webhook_id: str,
    limit: int = 50,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查一个订阅的投递记录（最新在前，默认最多 50 条）。"""
    items = await webhook_service.get_webhook_deliveries(db, user, webhook_id, limit=limit)
    return {
        "code": 0,
        "message": "ok",
        "data": DeliveryListResponse(
            items=[DeliveryItem(**i) for i in items],
            total=len(items),
        ),
    }


@router.post("/{webhook_id}/test", response_model=ApiResponse[WebhookTestResponse])
async def test_webhook(
    webhook_id: str,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """向订阅 URL 发一条测试事件，返回投递结果。

    用于创建订阅后验证连通性与签名校验是否正确；
    投递带重试（0.5s/2s/8s），失败结果同样落 delivery 记录。
    """
    delivery = await webhook_service.send_test_event(db, user, webhook_id)
    return {
        "code": 0,
        "message": "ok",
        "data": WebhookTestResponse(delivery=DeliveryItem(**delivery)),
    }


__all__ = ["router"]
