"""API Key 管理接口（W4-API-01）。

对外暴露机器调用凭据的签发、查询与吊销。签发走 JWT 用户身份；
机器调用侧的鉴权分流在 deps.get_current_user（hk_ 前缀）。

接口清单：
    POST   /api-keys          签发新 key（明文仅此一次返回）
    GET    /api-keys          列出租户下全部 key（脱敏）
    DELETE /api-keys/{id}     吊销一个 key（is_active=False，幂等）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from harness.platform.api.deps import get_db, require_role
from harness.platform.api.dto.api_key_dto import ApiKeyCreateRequest
from harness.platform.api.exceptions import BizError
from harness.platform.api.vo.api_key_vo import (
    ApiKeyCreateResponse,
    ApiKeyItem,
    ApiKeyListResponse,
    ApiKeyRevokeResponse,
)
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse
from harness.platform.service import api_key_service

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.post("", response_model=ApiResponse[ApiKeyCreateResponse])
async def create_api_key(
    body: ApiKeyCreateRequest,
    user: UserInfo = Depends(require_role("owner", "admin", "machine")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """签发一个新 API Key。

    明文只在本次响应里出现一次，前端需提示用户立即保存；
    服务端只落 SHA-256 哈希，丢了只能吊销重签。
    """
    result = await api_key_service.create_api_key(
        db,
        user=user,
        name=body.name,
        expires_in_days=body.expires_in_days,
    )
    return {
        "code": 0,
        "message": "ok",
        "data": ApiKeyCreateResponse(
            key=ApiKeyItem(**result["key"]),
            plaintext=result["plaintext"],
        ),
    }


@router.get("", response_model=ApiResponse[ApiKeyListResponse])
async def list_api_keys(
    user: UserInfo = Depends(require_role("owner", "admin", "machine")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出租户下全部 API Key（脱敏，不含哈希与明文）。"""
    items = await api_key_service.list_api_keys(db, user)
    return {
        "code": 0,
        "message": "ok",
        "data": ApiKeyListResponse(
            items=[ApiKeyItem(**i) for i in items],
            total=len(items),
        ),
    }


@router.delete("/{key_id}", response_model=ApiResponse[ApiKeyRevokeResponse])
async def revoke_api_key(
    key_id: str,
    user: UserInfo = Depends(require_role("owner", "admin", "machine")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """吊销一个 API Key（同租户校验）。

    - 不存在 → BizError(404)
    - 跨租户 → BizError(403)
    - 已吊销的重复吊销幂等返回 revoked=true
    """
    revoked = await api_key_service.revoke_api_key(db, user, key_id)
    if not revoked:
        raise BizError(status.HTTP_404_NOT_FOUND, f"api key {key_id} not found")
    return {
        "code": 0,
        "message": "ok",
        "data": ApiKeyRevokeResponse(revoked=True),
    }


__all__ = ["router"]
