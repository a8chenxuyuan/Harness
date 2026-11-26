"""租户配额接口（W3-PLAT-01）。

GET  /api/v1/tenant/quotas — 查看配额与当日用量
PUT  /api/v1/tenant/quotas — 调整配额（仅 owner / admin）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from harness.platform.api.deps import get_db, require_role
from harness.platform.api.dto.tenant_dto import QuotaUpdateRequest
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse

router = APIRouter(prefix="/tenant", tags=["tenant"])


@router.get("/quotas", response_model=ApiResponse[dict])
async def get_quotas(
    user: UserInfo = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查看当前租户配额、当日用量与并发数。"""
    from harness.platform.service.quota_service import QuotaService

    data = await QuotaService(db).summary(user.tenant_id)
    return {"code": 0, "message": "ok", "data": data}


@router.put("/quotas", response_model=ApiResponse[dict])
async def update_quotas(
    req: QuotaUpdateRequest,
    user: UserInfo = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """调整当前租户配额（仅 owner / admin）。"""
    from harness.platform.auth.audit import record_audit
    from harness.platform.service.quota_service import QuotaService

    data = await QuotaService(db).update(user.tenant_id, req.model_dump())
    await record_audit(
        db,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        action="tenant.quota.update",
        target=user.tenant_id,
        detail=req.model_dump(exclude_none=True),
    )
    return {"code": 0, "message": "ok", "data": data}


__all__ = ["router"]
