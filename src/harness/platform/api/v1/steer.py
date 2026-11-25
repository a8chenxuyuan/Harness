"""中途插话接口（原 gateway/server.py 里的 /api/steer）。

Controller 层只解析请求 + 调 Service，业务逻辑在 ``steering_api`` 里。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from harness.platform.api.deps import get_current_user
from harness.platform.api.dto.auth import UserInfo
from harness.platform.api.dto.common import ApiResponse
from harness.platform.api.dto.steer import SteerRequest, SteerResponse

router = APIRouter(prefix="/steer", tags=["steering"])


@router.post("", response_model=ApiResponse[SteerResponse])
async def steer(
    req: SteerRequest,
    user: UserInfo = Depends(get_current_user),
) -> dict:
    """对一个活动中的会话执行 interrupt / continue / inject。"""
    from harness.integrations.gateway.steering_api import steer as _steer

    result = await _steer(req)
    if result is None:
        raise HTTPException(status_code=404, detail=f"session {req.session_id} not found")

    return {
        "code": 0,
        "message": "ok",
        "data": SteerResponse(
            ok=True,
            session_id=req.session_id,
            action=req.kind,
        ),
    }
