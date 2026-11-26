"""认证应用服务 — Phase 22 完整实现（真实 DB，无降级）。

链路：
    login    → UserRepository.get_by_username → password.verify → jwt.sign × 2
    register → 查重 → UserRepository.save → jwt.sign × 2
    refresh  → jwt.decode(refresh) → 查 user.role → jwt.sign × 2

Session 由 Controller 层通过 ``Depends(get_db)`` 注入，请求结束自动关闭。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from harness.platform.api.dto.auth_dto import RegisterRequest
from harness.platform.api.vo.auth_vo import LoginResponse
from harness.platform.api.exceptions import BizError
from harness.platform.auth.jwt import (
    ACCESS_TOKEN_EXPIRE,
    decode_refresh_token,
    sign_access_token,
    sign_refresh_token,
)
from harness.platform.auth.password import hash_password, verify_password
from harness.platform.entity.refresh_token import RefreshToken
from harness.platform.entity.user import User
from harness.platform.repository.refresh_token_repository import (
    RefreshTokenRepository,
)
from harness.platform.repository.user_repository import UserRepository

# 开发期默认租户（多租户管理接口在 Phase 25+ 开放后动态创建）
DEFAULT_TENANT_ID = "dev-tenant"


class AuthService:
    """登录 / 注册 / token 刷新的业务编排。"""

    def __init__(self, session) -> None:
        self.users = UserRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)
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

        return await self._issue_tokens(user)

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

        return await self._issue_tokens(user)

    # ------------------------------------------------------------------
    # 刷新
    # ------------------------------------------------------------------

    async def refresh(self, refresh_token: str) -> LoginResponse:
        """用 refresh token 轮换出一对新 token。

        校验链：JWT 签名 → jti 记录存在 → 哈希一致 → 未被吊销 → 未过期。
        旧 token 被重复使用时视为重放，吊销该用户全部 refresh token。
        role 从 DB 实时取，避免角色变更后旧 refresh 仍带旧权限。
        """
        payload = decode_refresh_token(refresh_token)
        if payload is None:
            raise BizError(401, "invalid or expired refresh token")

        record = await self.refresh_tokens.get(payload["jti"])
        if record is None or record.token_hash != _hash_token(refresh_token):
            raise BizError(401, "refresh token 不存在或已被替换")

        if record.revoked_at is not None:
            # 重放：旧 token 已轮换过，直接吊销该用户全部 refresh token
            await self.refresh_tokens.revoke_all_for_user(payload["sub"])
            raise BizError(401, "refresh token 已失效，请重新登录")

        if _as_utc(record.expires_at) <= datetime.now(timezone.utc):
            await self.refresh_tokens.revoke(payload["jti"])
            raise BizError(401, "refresh token 已过期")

        user = await self.users.get(payload["sub"])
        if user is None or not user.is_active:
            raise BizError(401, "user not found or disabled")

        access_token, _ = sign_access_token(user.id, user.tenant_id, user.role)
        new_refresh_token, _ = sign_refresh_token(user.id, user.tenant_id)
        new_record = self._build_refresh_record(new_refresh_token, user)
        await self.refresh_tokens.rotate(record, new_record)

        return LoginResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_in=ACCESS_TOKEN_EXPIRE,
        )

    async def revoke_refresh_token(self, refresh_token: str | None) -> bool:
        """登出：吊销指定 refresh token（非法/空 token 静默忽略）。"""
        if not refresh_token:
            return False
        payload = decode_refresh_token(refresh_token)
        if payload is None:
            return False
        return await self.refresh_tokens.revoke(payload["jti"])

    # ------------------------------------------------------------------
    # 内部：签发与落库
    # ------------------------------------------------------------------

    async def _issue_tokens(self, user: User) -> LoginResponse:
        """签发 access + refresh，并把 refresh 记录落库。"""
        access_token, _ = sign_access_token(user.id, user.tenant_id, user.role)
        refresh_token, _ = sign_refresh_token(user.id, user.tenant_id)
        await self.refresh_tokens.add(
            self._build_refresh_record(refresh_token, user)
        )
        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=ACCESS_TOKEN_EXPIRE,
        )

    @staticmethod
    def _build_refresh_record(token: str, user: User) -> RefreshToken:
        """从刚签发的 token 中取 jti / exp，构造待落库记录。"""
        payload = decode_refresh_token(token)
        if payload is None:  # 理论上不会发生：刚签发的 token 必然可解析
            raise BizError(500, "refresh token 签发异常")
        return RefreshToken(
            jti=payload["jti"],
            user_id=user.id,
            tenant_id=user.tenant_id,
            token_hash=_hash_token(token),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        )


def _hash_token(token: str) -> str:
    """refresh token 的 SHA-256 哈希（不落明文）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    """SQLite 取回的 datetime 可能无时区，统一按 UTC 处理。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
