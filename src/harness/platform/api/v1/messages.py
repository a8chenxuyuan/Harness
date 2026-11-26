"""会话消息接口：GET / POST /api/v1/sessions/{session_id}/messages。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from harness.platform.api.deps import get_current_user, get_db
from harness.platform.api.dto.message_dto import MessageCreateRequest
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse
from harness.platform.api.vo.message_vo import (
    MessageBranchResponse,
    MessageListResponse,
    MessageResponse,
    MessageRetryResponse,
)
from harness.platform.service.rate_limit import message_rate_limit

router = APIRouter(prefix="/sessions/{session_id}/messages", tags=["messages"])


@router.get("", response_model=ApiResponse[MessageListResponse])
async def list_messages(
    session_id: str,
    after_seq: int = Query(default=0, ge=0, description="只返回 seq 大于该值的消息"),
    limit: int = Query(default=50, ge=1, le=200),
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """按 seq 游标分页读取会话消息（升序）。"""
    from harness.platform.service.message_service import MessageService

    result = await MessageService(user, db).list_messages(
        session_id, after_seq=after_seq, limit=limit
    )
    return {"code": 0, "message": "ok", "data": result}


@router.post("", response_model=ApiResponse[MessageResponse])
async def create_message(
    session_id: str,
    req: MessageCreateRequest,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _rate: None = Depends(message_rate_limit),
) -> dict:
    """追加一条消息，并刷新会话的 message_count / last_message_at。"""
    from harness.platform.auth.audit import record_audit
    from harness.platform.service.message_service import MessageService

    result = await MessageService(user, db).append_message(session_id, req)
    await record_audit(
        db,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        action="message.create",
        target=result.id,
        session_id=session_id,
        detail={"role": result.role, "seq": result.seq},
    )
    return {"code": 0, "message": "ok", "data": result}


@router.post(
    "/{message_id}/retry", response_model=ApiResponse[MessageRetryResponse]
)
async def retry_message(
    session_id: str,
    message_id: str,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """重试失败 / 取消的助手消息：软删旧问答并返回用户原文。"""
    from harness.platform.auth.audit import record_audit
    from harness.platform.service.message_action_service import (
        MessageActionService,
    )

    result = await MessageActionService(user, db).retry(session_id, message_id)
    await record_audit(
        db,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        action="message.retry",
        target=message_id,
        session_id=session_id,
        detail={"removed": result.removed_message_ids},
    )
    return {"code": 0, "message": "ok", "data": result}


@router.post(
    "/{message_id}/branch", response_model=ApiResponse[MessageBranchResponse]
)
async def branch_message(
    session_id: str,
    message_id: str,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """以指定消息为分界复制历史到新会话。"""
    from harness.platform.auth.audit import record_audit
    from harness.platform.service.message_action_service import (
        MessageActionService,
    )

    result = await MessageActionService(user, db).branch(session_id, message_id)
    await record_audit(
        db,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        action="message.branch",
        target=message_id,
        session_id=session_id,
        detail={"branch_session_id": result.session_id},
    )
    return {"code": 0, "message": "ok", "data": result}


__all__ = ["router"]
