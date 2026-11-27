"""权限管理接口（W4.1-WEB-01）。

接口清单（全部 owner / admin）：
    GET  /permissions/matrix               页面清单 + 角色×页面矩阵
    PUT  /permissions/matrix               改单格 {role, page_key, allowed}
    GET  /permissions/users                租户用户列表 + 各自角色
    PUT  /permissions/users/{id}/roles     全量替换某用户角色（多角色）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from harness.platform.api.deps import get_db, require_role
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse
from harness.platform.service import permission_service as svc

router = APIRouter(prefix="/permissions", tags=["permissions"])


# ---------------------------------------------------------------------------
# VO
# ---------------------------------------------------------------------------

class MatrixResponse(BaseModel):
    """页面清单 + 矩阵（含 owner 只读行，前端禁用其开关）。"""

    pages: list[str]
    roles: list[str]
    matrix: dict[str, dict[str, bool]]
    default_matrix: dict[str, list[str]]


class MatrixUpdateRequest(BaseModel):
    role: str
    page_key: str
    allowed: bool


class UserRoleItem(BaseModel):
    user_id: str
    username: str
    email: str
    primary_role: str
    roles: list[str]
    is_active: bool


class UsersResponse(BaseModel):
    items: list[UserRoleItem]


class UserRolesUpdateRequest(BaseModel):
    roles: list[str]


class UserRolesResponse(BaseModel):
    user_id: str
    roles: list[str]
    primary_role: str


# ---------------------------------------------------------------------------
# 矩阵
# ---------------------------------------------------------------------------

@router.get("/matrix", response_model=ApiResponse[MatrixResponse])
async def get_matrix(
    admin: UserInfo = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """读角色×页面矩阵（owner 行为保底全量，仅展示）。"""
    matrix = await svc._load_matrix(db, admin.tenant_id)
    # owner 行展示为全量 true（代码保底），提示前端禁用
    display = {role: dict(pages) for role, pages in matrix.items()}
    display["owner"] = {page: True for page in svc.PAGE_KEYS}
    return {
        "code": 0,
        "message": "ok",
        "data": MatrixResponse(
            pages=list(svc.PAGE_KEYS),
            roles=["owner", "admin", "member"],
            matrix=display,
            default_matrix={r: sorted(p) for r, p in svc.DEFAULT_MATRIX.items()},
        ),
    }


@router.put("/matrix", response_model=ApiResponse[dict])
async def update_matrix(
    body: MatrixUpdateRequest,
    admin: UserInfo = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """改单格矩阵（owner 行拒绝）。"""
    entry = await svc.set_page_permission(
        db, admin.tenant_id, body.role, body.page_key, body.allowed, admin.user_id
    )
    return {"code": 0, "message": "ok", "data": entry}


# ---------------------------------------------------------------------------
# 用户角色分配
# ---------------------------------------------------------------------------

@router.get("/users", response_model=ApiResponse[UsersResponse])
async def list_permission_users(
    admin: UserInfo = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出租户全部用户及其角色（多角色）。"""
    items = await svc.list_users_with_roles(db, admin.tenant_id)
    return {
        "code": 0,
        "message": "ok",
        "data": UsersResponse(items=[UserRoleItem(**i) for i in items]),
    }


@router.put("/users/{user_id}/roles", response_model=ApiResponse[UserRolesResponse])
async def update_user_roles(
    user_id: str,
    body: UserRolesUpdateRequest,
    admin: UserInfo = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """全量替换某用户的角色列表（多角色），同步主角色。"""
    result = await svc.set_user_roles(
        db, admin.tenant_id, user_id, body.roles, admin.user_id
    )
    return {"code": 0, "message": "ok", "data": UserRolesResponse(**result)}


__all__ = ["router"]
