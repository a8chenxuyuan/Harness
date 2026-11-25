"""认证接口（register / login / refresh / logout / me）。

Controller 只做参数校验 + 调 Service + 返回统一响应；
DB Session 通过 ``Depends(get_db)`` 注入，请求结束自动关闭。
成功路径统一写审计日志（``platform.auth.audit.record_audit``）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from harness.platform.api.deps import get_current_user, get_db
from harness.platform.api.dto.auth_dto import LoginRequest, RefreshRequest, RegisterRequest
from harness.platform.api.vo.auth_vo import LoginResponse, UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _claims(token: str) -> dict | None:
    """从刚签发的 access token 里取 sub / tid（供审计用）。"""
    from harness.platform.auth.jwt import decode_access_token
    return decode_access_token(token)


@router.post("/register", response_model=ApiResponse[LoginResponse])
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """新用户注册 + 自动登录（bcrypt 哈希 + 双 token）。"""
    from harness.platform.auth.audit import record_audit
    from harness.platform.service.auth_service import AuthService

    result = await AuthService(db).register(req)
    claims = _claims(result.access_token)
    if claims:
        await record_audit(
            db,
            tenant_id=claims["tid"],
            user_id=claims["sub"],
            action="auth.register",
            target=req.username,
        )
    return {"code": 0, "message": "ok", "data": result}


@router.post("/login", response_model=ApiResponse[LoginResponse])
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """用户登录（username + password → access/refresh token）。"""
    from harness.platform.auth.audit import record_audit
    from harness.platform.service.auth_service import AuthService

    result = await AuthService(db).login(req.username, req.password)
    claims = _claims(result.access_token)
    if claims:
        await record_audit(
            db,
            tenant_id=claims["tid"],
            user_id=claims["sub"],
            action="auth.login",
            target=req.username,
        )
    return {"code": 0, "message": "ok", "data": result}


@router.post("/refresh", response_model=ApiResponse[LoginResponse])
async def refresh_token(
    req: RefreshRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    """用 refresh token 换一对新 token（role 实时从 DB 取）。"""
    from harness.platform.auth.audit import record_audit
    from harness.platform.service.auth_service import AuthService

    result = await AuthService(db).refresh(req.refresh_token)
    claims = _claims(result.access_token)
    if claims:
        await record_audit(
            db,
            tenant_id=claims["tid"],
            user_id=claims["sub"],
            action="auth.refresh",
        )
    return {"code": 0, "message": "ok", "data": result}


@router.post("/logout", response_model=ApiResponse[dict])
async def logout(
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """登出。无 Redis 黑名单时只写审计并返回成功（token 由客户端丢弃）。"""
    from harness.platform.auth.audit import record_audit

    await record_audit(
        db,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        action="auth.logout",
    )
    return {"code": 0, "message": "ok", "data": {"user_id": user.user_id}}


@router.get("/me", response_model=ApiResponse[UserInfo])
async def me(user: UserInfo = Depends(get_current_user)) -> dict:
    """返回当前登录用户的信息（从 JWT 解析）。"""
    return {"code": 0, "message": "ok", "data": user}
