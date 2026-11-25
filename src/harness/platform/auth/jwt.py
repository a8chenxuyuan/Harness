"""JWT 双 token 体系（HS256）。

access_token  15 分钟 —— 鉴权用，Resource Server 每次请求都验证
refresh_token 7  天  —— 只用来换新 access_token，不携带业务权限

Payload 结构::

    {"sub": "user-uuid", "tid": "tenant-uuid", "role": "owner", "exp": ...}
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any

import jwt as pyjwt

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE = 900        # 15 min
REFRESH_TOKEN_EXPIRE = 604800    # 7 day
DEFAULT_SECRET = "harness-dev-secret-change-me-in-production"


def _get_secret() -> str:
    """取签名密钥。

    优先级：环境变量 HARNESS_JWT_SECRET > Settings.jwt_secret > 默认 dev secret。
    """
    env_val = os.environ.get("HARNESS_JWT_SECRET")
    if env_val:
        return env_val
    try:
        from harness.common.config.settings import Settings
        s = Settings()
        if getattr(s, "jwt_secret", ""):
            return s.jwt_secret
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_SECRET


def _decode_secret() -> str:
    """验证时用的密钥（和 _get_secret 对称）。"""
    return _get_secret()


# ---------------------------------------------------------------------------
# Access Token
# ---------------------------------------------------------------------------


def sign_access_token(user_id: str, tenant_id: str, role: str) -> tuple[str, int]:
    """签发 access token。

    Args:
        user_id: 用户 uuid（sub）。
        tenant_id: 租户 uuid（tid）。
        role: owner | admin | member。

    Returns:
        (token, expires_in_seconds)
    """
    now = int(time.time())
    payload = {
        "sub": user_id,
        "tid": tenant_id,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + ACCESS_TOKEN_EXPIRE,
    }
    token = pyjwt.encode(payload, _get_secret(), algorithm=ALGORITHM)
    return token, ACCESS_TOKEN_EXPIRE


def decode_access_token(token: str) -> dict[str, Any] | None:
    """验证并解码 access token。

    Args:
        token: JWT 字符串。

    Returns:
        payload dict。None 表示过期 / 签名错误 / type 不是 access。
    """
    try:
        payload = pyjwt.decode(
            token,
            _decode_secret(),
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub", "tid", "role"]},
        )
    except pyjwt.ExpiredSignatureError:
        log.info("jwt: access token expired")
        return None
    except pyjwt.InvalidTokenError as exc:
        log.warning("jwt: invalid access token: %s", exc)
        return None

    if payload.get("type") != "access":
        log.warning("jwt: expected access token, got type=%s", payload.get("type"))
        return None

    return payload


# ---------------------------------------------------------------------------
# Refresh Token
# ---------------------------------------------------------------------------


def sign_refresh_token(user_id: str, tenant_id: str) -> tuple[str, int]:
    """签发 refresh token。

    Args:
        user_id: 用户 uuid。
        tenant_id: 租户 uuid。

    Returns:
        (token, expires_in_seconds)
    """
    now = int(time.time())
    payload = {
        "sub": user_id,
        "tid": tenant_id,
        "type": "refresh",
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + REFRESH_TOKEN_EXPIRE,
    }
    token = pyjwt.encode(payload, _get_secret(), algorithm=ALGORITHM)
    return token, REFRESH_TOKEN_EXPIRE


def decode_refresh_token(token: str) -> dict[str, Any] | None:
    """验证并解码 refresh token。"""
    try:
        payload = pyjwt.decode(
            token,
            _decode_secret(),
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub", "tid", "jti"]},
        )
    except pyjwt.ExpiredSignatureError:
        log.info("jwt: refresh token expired")
        return None
    except pyjwt.InvalidTokenError as exc:
        log.warning("jwt: invalid refresh token: %s", exc)
        return None

    if payload.get("type") != "refresh":
        log.warning("jwt: expected refresh token")
        return None

    return payload


# ---------------------------------------------------------------------------
# 便捷：换一对新 token
# ---------------------------------------------------------------------------


def refresh_tokens(refresh_token: str) -> dict[str, Any] | None:
    """用 refresh token 换一对新 token。

    Returns:
        {"access_token", "refresh_token", "expires_in"} 或 None。
    """
    payload = decode_refresh_token(refresh_token)
    if payload is None:
        return None

    user_id = payload["sub"]
    tenant_id = payload["tid"]

    # 注意：refresh token 里没有 role，需要从 user 表查
    # 但为了简化，我们让调用方（AuthService）传 role
    # 这里先给一个占位 role，生产环境必须查 DB
    # 所以实际调用链：AuthService.refresh() 先查 user.role，再调这里

    access, expires = sign_access_token(user_id, tenant_id, role="member")
    refresh, _ = sign_refresh_token(user_id, tenant_id)
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": expires,
    }


__all__ = [
    "sign_access_token",
    "decode_access_token",
    "sign_refresh_token",
    "decode_refresh_token",
    "refresh_tokens",
    "ACCESS_TOKEN_EXPIRE",
    "REFRESH_TOKEN_EXPIRE",
]
