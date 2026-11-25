"""Session 管理接口（真实 DB，租户隔离）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from harness.platform.api.deps import get_current_user, get_db
from harness.platform.api.dto.auth import UserInfo
from harness.platform.api.dto.common import ApiResponse
from harness.platform.api.dto.session import (
    SessionCreateRequest,
    SessionListResponse,
    SessionResponse,
)

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
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """分页列出当前用户的会话（创建时间倒序）。"""
    from harness.platform.service.session_service import SessionService
    result = await SessionService(user, db).list_sessions(page, size)
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
