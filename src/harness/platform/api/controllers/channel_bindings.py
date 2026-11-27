"""渠道绑定管理接口（W4-CHAN-05）。

接口清单：
    GET    /channels/bindings            当前用户的全部绑定
    DELETE /channels/bindings/{binding_id}  注销一条绑定（仅本人，幂等）

绑定创建只能通过 OAuth 登录流程（/auth/wecom/callback）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from harness.platform.api.deps import get_current_user, get_db
from harness.platform.api.exceptions import BizError
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.channel_binding_vo import (
    BindingItem,
    BindingListResponse,
    BindingRevokeResponse,
)
from harness.platform.api.vo.envelope_vo import ApiResponse
from harness.platform.repository.channel_binding_repository import (
    ChannelBindingRepository,
)

router = APIRouter(prefix="/channels/bindings", tags=["channel-bindings"])


@router.get("", response_model=ApiResponse[BindingListResponse])
async def list_bindings(
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列当前用户的全部渠道绑定（脱敏，不含凭证密文）。"""
    repo = ChannelBindingRepository(db)
    records = await repo.list_for_user(user.user_id)
    items = [
        BindingItem(
            id=b.id,
            platform=b.platform,
            platform_user_id=b.platform_user_id,
            display_name=b.display_name,
            status=b.status,
            last_login_at=b.last_login_at.isoformat() if b.last_login_at else None,
            created_at=b.created_at.isoformat(),
        )
        for b in records
    ]
    return {"code": 0, "message": "ok", "data": BindingListResponse(items=items, total=len(items))}


@router.delete("/{binding_id}", response_model=ApiResponse[BindingRevokeResponse])
async def revoke_binding(
    binding_id: str,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """注销一条绑定（同用户校验；幂等）。

    - 不存在 → 404
    - 非本人绑定 → 403（防越权）
    """
    repo = ChannelBindingRepository(db)
    binding = await repo.get(binding_id)
    if binding is None:
        raise BizError(status.HTTP_404_NOT_FOUND, f"binding {binding_id} not found")
    if binding.harness_user_id != user.user_id:
        raise BizError(status.HTTP_403_FORBIDDEN, "无权注销他人的绑定")
    await repo.revoke(binding_id)
    return {"code": 0, "message": "ok", "data": BindingRevokeResponse(revoked=True)}


__all__ = ["router"]
