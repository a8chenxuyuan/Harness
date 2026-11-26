"""计划查询接口（GET /plans、GET /plans/{id}）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from harness.platform.api.deps import get_current_user, get_db
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse
from harness.platform.api.vo.plan_vo import PlanListResponse, PlanSummary
from harness.platform.repository.plan_repository import PlanRepository
from harness.platform.service.plan_service import PlanService

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("", response_model=ApiResponse[PlanListResponse])
async def list_plans(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """分页列出当前租户的计划（创建时间倒序）。"""
    records, total = await PlanService(db, user).list_plans(page, size)
    items = [PlanSummary(**PlanRepository.to_dict(r)) for r in records]
    return {
        "code": 0,
        "message": "ok",
        "data": {"items": items, "total": total, "page": page, "size": size},
    }


@router.get("/{plan_id}", response_model=ApiResponse[PlanSummary])
async def get_plan(
    plan_id: str,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询单个计划（租户隔离，跨租户 404）。"""
    record = await PlanService(db, user).get(plan_id)
    return {
        "code": 0,
        "message": "ok",
        "data": PlanSummary(**PlanRepository.to_dict(record)),
    }


__all__ = ["router"]
