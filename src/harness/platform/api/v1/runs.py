"""运行记录接口：GET /api/v1/runs、GET /api/v1/runs/{run_id}。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from harness.platform.api.deps import get_current_user, get_db
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse
from harness.platform.api.vo.run_vo import RunListResponse, RunResponse

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=ApiResponse[RunListResponse])
async def list_runs(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None, description="按状态过滤"),
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """分页列出当前用户的运行记录（创建时间倒序）。"""
    from harness.platform.service.run_service import RunService

    result = await RunService(user, db).list_runs(
        page=page, size=size, status=status
    )
    return {"code": 0, "message": "ok", "data": result}


@router.get("/{run_id}", response_model=ApiResponse[RunResponse])
async def get_run(
    run_id: str,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取运行详情（租户 + 发起人隔离）。"""
    from harness.platform.service.run_service import RunService

    result = await RunService(user, db).get_run(run_id)
    return {"code": 0, "message": "ok", "data": result}


__all__ = ["router"]
