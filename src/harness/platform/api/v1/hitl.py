"""人机协作（HITL）接口（原 gateway/server.py 里的 /api/hitl/*）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from harness.platform.api.deps import get_current_user
from harness.platform.api.dto.auth import UserInfo
from harness.platform.api.dto.common import ApiResponse

router = APIRouter(prefix="/hitl", tags=["hitl"])


@router.post("/approve", response_model=ApiResponse[dict])
async def approve(
    request_id: str,
    reason: str = "approved",
    user: UserInfo = Depends(get_current_user),
) -> dict:
    """批准一个挂起的 HITL 请求。"""
    from harness.platform.service.hitl_service import HitlService
    try:
        result = await HitlService().approve(request_id, reason)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"request {request_id} not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"code": 0, "message": "ok", "data": {"status": result.status}}


@router.post("/deny", response_model=ApiResponse[dict])
async def deny(
    request_id: str,
    reason: str = "denied",
    user: UserInfo = Depends(get_current_user),
) -> dict:
    """拒绝一个挂起的 HITL 请求。"""
    from harness.platform.service.hitl_service import HitlService
    try:
        result = await HitlService().deny(request_id, reason)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"request {request_id} not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"code": 0, "message": "ok", "data": {"status": result.status}}
