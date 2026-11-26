"""Session 管理接口（真实 DB，租户隔离）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from harness.platform.api.deps import get_current_user, get_db
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse
from harness.platform.api.dto.session_dto import SessionCreateRequest
from harness.platform.api.vo.session_vo import SessionListResponse, SessionResponse

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=ApiResponse[SessionResponse])
async def create_session(
    req: SessionCreateRequest,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建新会话。"""
    from harness.platform.service.session_service import SessionService
    result = await SessionService(user, db).create_session(req.title, req.metadata)
    return {"code": 0, "message": "ok", "data": result}


@router.get("", response_model=ApiResponse[SessionListResponse])
async def list_sessions(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(
        default=None,
        pattern="^(active|archived|all)$",
        description="按状态过滤；不传或 all 表示全部",
    ),
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """分页列出当前用户的会话（创建时间倒序），支持状态过滤。"""
    from harness.platform.service.session_service import SessionService
    result = await SessionService(user, db).list_sessions(page, size, status)
    return {"code": 0, "message": "ok", "data": result}


@router.get("/{session_id}", response_model=ApiResponse[SessionResponse])
async def get_session(
    session_id: str,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取指定会话详情（租户隔离）。"""
    from harness.platform.service.session_service import SessionService
    result = await SessionService(user, db).get_session(session_id)
    return {"code": 0, "message": "ok", "data": result}


@router.post(
    "/{session_id}/archive", response_model=ApiResponse[SessionResponse]
)
async def archive_session(
    session_id: str,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """归档会话（从默认工作列表移出，消息保留）。"""
    from harness.platform.auth.audit import record_audit
    from harness.platform.service.session_service import SessionService

    result = await SessionService(user, db).archive_session(session_id)
    await record_audit(
        db,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        action="session.archive",
        target=session_id,
    )
    return {"code": 0, "message": "ok", "data": result}


@router.post(
    "/{session_id}/unarchive", response_model=ApiResponse[SessionResponse]
)
async def unarchive_session(
    session_id: str,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """恢复已归档会话。"""
    from harness.platform.auth.audit import record_audit
    from harness.platform.service.session_service import SessionService

    result = await SessionService(user, db).archive_session(
        session_id, archived=False
    )
    await record_audit(
        db,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        action="session.unarchive",
        target=session_id,
    )
    return {"code": 0, "message": "ok", "data": result}


@router.delete("/{session_id}", response_model=ApiResponse[dict[str, Any]])
async def delete_session(
    session_id: str,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除指定会话（租户隔离）。"""
    from harness.platform.service.session_service import SessionService
    await SessionService(user, db).delete_session(session_id)
    return {"code": 0, "message": "ok", "data": {"session_id": session_id}}
