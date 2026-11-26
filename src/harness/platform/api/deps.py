"""FastAPI 依赖注入（对应 Java Spring 的 @Value / @Autowired）。

统一管理：
    - get_db — 数据库 AsyncSession（Yields，请求结束自动 close）
    - get_current_user — 从 JWT 解析当前用户（开发模式占位保留）
    - get_gateway_router — GatewayRouter 单例
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, Header, HTTPException, status

from harness.platform.api.vo.auth_vo import UserInfo

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GatewayRouter 单例
# ---------------------------------------------------------------------------

_gateway_router: Any = None


def set_gateway_router(router: Any) -> None:
    """注入 GatewayRouter（应用启动时调用一次）。"""
    global _gateway_router
    _gateway_router = router


def get_gateway_router() -> Any:
    """FastAPI dependency：返回 GatewayRouter 单例。"""
    if _gateway_router is None:
        from harness.integrations.gateway import GatewayRouter
        _gateway_router = GatewayRouter()
    return _gateway_router


# ---------------------------------------------------------------------------
# 数据库 Session
# ---------------------------------------------------------------------------

async def get_db():
    """FastAPI dependency：yield 一个 AsyncSession，请求结束自动 close。

    底层用 ``harness.platform.infra.engine.get_session_factory`` 单例。
    """
    from harness.platform.infra.engine import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        yield session


# ---------------------------------------------------------------------------
# 认证：从 Authorization Bearer 解析 JWT 或 API Key（W4-API-01 起双轨）
# ---------------------------------------------------------------------------

def _dev_mode() -> bool:
    """读取开发模式开关（默认 False）。

    优先级：env ``HARNESS_DEV_MODE`` > ``Settings.dev_mode``。
    生产环境必须保持关闭。
    """
    import os

    env_val = os.environ.get("HARNESS_DEV_MODE")
    if env_val is not None:
        return env_val.strip().lower() in ("1", "true", "yes", "on")
    try:
        from harness.common.config.settings import Settings
        return bool(getattr(Settings(), "dev_mode", False))
    except Exception:  # noqa: BLE001
        return False


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: Any = Depends(get_db),
) -> UserInfo:
    """FastAPI dependency：从 Bearer 头解析当前调用者。

    按 token 前缀双轨分流（W4-API-01）：
        - ``hk_`` 开头 → API Key 机器调用：哈希查表校验，
          role 记为 "machine"（api_key_service.authenticate_key）
        - 其他        → 用户 JWT：decode 校验，role 取 payload

    生产模式：
        - 没有 token → 401
        - token 过期 / 签名错 / 格式错 / key 失效 → 401
        - 校验成功 → 返回 UserInfo(user_id, tenant_id, role)

    开发模式（Settings.dev_mode=True）：
        - 没有 token → 返回默认租户的 owner（方便本地调试）
        - 有 token 就真的校验
    """
    # 开发模式：没有 token 也放行
    if authorization is None:
        if _dev_mode():
            return UserInfo(
                user_id="dev-user",
                tenant_id="dev-tenant",
                role="owner",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing authorization header",
        )

    # 解析 Bearer <token>
    try:
        scheme, token = authorization.split(" ", 1)
        if scheme.lower() != "bearer":
            raise ValueError("invalid scheme")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authorization header",
        )

    # API Key 双轨：hk_ 前缀 → 哈希查表（JWT 是三段 base64，必然不带 hk_ 前缀）
    from harness.platform.service.api_key_service import API_KEY_PREFIX

    if token.startswith(API_KEY_PREFIX):
        from harness.platform.service.api_key_service import authenticate_key

        user = await authenticate_key(db, token)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or revoked api key",
            )
        return user

    # 用户 JWT 轨
    from harness.platform.auth.jwt import decode_access_token
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
        )

    return UserInfo(
        user_id=payload["sub"],
        tenant_id=payload["tid"],
        role=payload.get("role", "member"),
    )


def require_role(*allowed_roles: str):
    """FastAPI dependency factory：限制只有指定角色能访问。

    用法::

        @router.delete("/{user_id}")
        async def delete_user(
            user_id: str,
            user: UserInfo = Depends(require_role("owner")),
        ): ...
    """

    def _dep(user: UserInfo = Depends(get_current_user)) -> UserInfo:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role {user.role} not in {allowed_roles}",
            )
        return user

    return _dep


__all__ = [
    "get_gateway_router",
    "set_gateway_router",
    "get_db",
    "get_current_user",
    "require_role",
]
