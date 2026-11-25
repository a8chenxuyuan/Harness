"""bcrypt 密码哈希 / 验证。

直接用 bcrypt（不经过 passlib），避免 passlib 与 bcrypt 5.x 的版本冲突。
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _ensure_bytes(text: str) -> bytes:
    """bcrypt 要求 bytes；同时确保不超 72 字节。"""
    data = text.encode("utf-8")
    # bcrypt 原生限制 72 字节
    if len(data) > 72:
        log.warning("password > 72 bytes, truncating")
        data = data[:72]
    return data


def hash_password(plain: str) -> str:
    """对明文密码做 bcrypt 哈希。

    Args:
        plain: 明文密码（任意长度，超过 72 字节自动截断）。

    Returns:
        bcrypt 哈希字符串（UTF-8 解码），直接存数据库。
    """
    import bcrypt
    return bcrypt.hashpw(_ensure_bytes(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """验证明文密码和 bcrypt 哈希是否匹配。

    Args:
        plain: 明文密码。
        hashed: 数据库存的哈希（UTF-8 字符串）。

    Returns:
        True 匹配。False 不匹配或 hashed 不是有效 bcrypt 格式。
    """
    try:
        import bcrypt
        return bool(bcrypt.checkpw(_ensure_bytes(plain), hashed.encode("utf-8")))
    except Exception as exc:  # noqa: BLE001
        log.warning("password.verify: bcrypt check failed: %s", exc)
        return False


__all__ = ["hash_password", "verify_password"]
