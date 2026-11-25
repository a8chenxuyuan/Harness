"""认证应用服务 — Phase 22 完整实现（真实 DB，无降级）。

链路：
    login    → UserRepository.get_by_username → password.verify → jwt.sign × 2
    register → 查重 → UserRepository.save → jwt.sign × 2
    refresh  → jwt.decode(refresh) → 查 user.role → jwt.sign × 2

Session 由 Controller 层通过 ``Depends(get_db)`` 注入，请求结束自动关闭。
"""

from __future__ import annotations

import uuid

from harness.platform.api.dto.auth import LoginResponse, RegisterRequest
from harness.platform.api.exceptions import BizError
from harness.platform.auth.jwt import (
    ACCESS_TOKEN_EXPIRE,
    decode_refresh_token,
    sign_access_token,
    sign_refresh_token,
)
from harness.platform.auth.password import hash_password, verify_password
from harness.platform.models.user import User
from harness.platform.repository.user_repo import UserRepository

# 开发期默认租户（多租户管理接口在 Phase 25+ 开放后动态创建）
DEFAULT_TENANT_ID = "dev-tenant"


class AuthService:
    """登录 / 注册 / token 刷新的业务编排。"""

    def __init__(self, session) -> None:
        self.users = UserRepository(session)
        self.session = session

    # ------------------------------------------------------------------
    # 登录
    # ------------------------------------------------------------------

    async def login(self, username: str, password: str) -> LoginResponse:
        """验证用户名密码，返回双 token。

        Raises:
            BizError(401): 用户名或密码错 / 账号禁用。
        """
        user = await self.users.get_by_username(DEFAULT_TENANT_ID, username)
        if user is None:
            # 不泄露"用户名不存在"，统一 401
            raise BizError(401, "用户名或密码错误")

        if not verify_password(password, user.hashed_password):
            raise BizError(401, "用户名或密码错误")

        if not user.is_active:
            raise BizError(401, "账号已禁用")

        access_token, _ = sign_access_token(user.id, user.tenant_id, user.role)
        refresh_token, _ = sign_refresh_token(user.id, user.tenant_id)

        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=ACCESS_TOKEN_EXPIRE,
        )

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------

    async def register(self, req: RegisterRequest) -> LoginResponse:
        """新用户注册 + 自动登录。

        Raises:
            BizError(409): 用户名已存在。
        """
        existing = await self.users.get_by_username(DEFAULT_TENANT_ID, req.username)
        if existing is not None:
            raise BizError(409, f"用户名 {req.username} 已存在")

        user = User(
            id=str(uuid.uuid4()),
            tenant_id=DEFAULT_TENANT_ID,
            username=req.username,
            email=req.email,
            hashed_password=hash_password(req.password),
            role="member",
            is_active=True,
        )
        await self.users.save(user)

        access_token, _ = sign_access_token(user.id, user.tenant_id, user.role)
        refresh_token, _ = sign_refresh_token(user.id, user.tenant_id)

        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=ACCESS_TOKEN_EXPIRE,
        )

    # ------------------------------------------------------------------
    # 刷新
    # ------------------------------------------------------------------

    async def refresh(self, refresh_token: str) -> LoginResponse:
        """用 refresh token 换一对新 token。

        role 从 DB 实时取，避免角色变更后旧 refresh 仍带旧权限。
        """
        payload = decode_refresh_token(refresh_token)
        if payload is None:
            raise BizError(401, "invalid or expired refresh token")

        user = await self.users.get(payload["sub"])
        if user is None or not user.is_active:
            raise BizError(401, "user not found or disabled")

        access_token, _ = sign_access_token(user.id, user.tenant_id, user.role)
        new_refresh_token, _ = sign_refresh_token(user.id, user.tenant_id)

        return LoginResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_in=ACCESS_TOKEN_EXPIRE,
        )
