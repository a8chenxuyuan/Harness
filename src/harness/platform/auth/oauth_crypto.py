"""渠道 OAuth 凭证加密助手（W4-CHAN-05）。

Encrypt-then-MAC：AES-256-CBC 加密 + HMAC-SHA256 完整性校验。
密钥来源（二选一）：
    1. env ``HARNESS_OAUTH_ENC_KEY``（任意 ≥16 字符字符串，SHA-256 派生）
    2. 缺省从 ``HARNESS_JWT_SECRET`` 派生（开发环境零配置）

密文格式：base64( iv(16B) + ciphertext + mac(32B) )
MAC 覆盖 iv + ciphertext。

注意：换密钥后旧密文不可解密——换钥前需先把存量凭证解出来重加密，
或让用户重新授权。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import uuid
from typing import Any

try:
    from Crypto.Cipher import AES  # type: ignore
except Exception:  # noqa: BLE001
    AES = None  # type: ignore[assignment]


class OAuthCryptoError(RuntimeError):
    """加解密失败（密钥变更 / 密文损坏 / MAC 不匹配）。"""


def _derive_key() -> bytes:
    """从 env 取密钥材料并派生 32 字节 AESKey。"""
    material = os.environ.get("HARNESS_OAUTH_ENC_KEY") or os.environ.get(
        "HARNESS_JWT_SECRET"
    )
    if not material:
        raise OAuthCryptoError("HARNESS_OAUTH_ENC_KEY / HARNESS_JWT_SECRET 均未配置")
    return hashlib.sha256(material.encode("utf-8")).digest()


def encrypt_credential(plaintext: str | dict[str, Any]) -> str:
    """加密字符串或 dict（dict 先转 JSON），返回 base64 密文。"""
    if AES is None:
        raise OAuthCryptoError("pycryptodome 未安装，无法加密凭证")
    if isinstance(plaintext, dict):
        plaintext = json.dumps(plaintext, ensure_ascii=False)
    data = plaintext.encode("utf-8")

    key = _derive_key()
    iv = os.urandom(16)
    pad_len = 16 - len(data) % 16
    padded = data + bytes([pad_len] * pad_len)
    ciphertext = AES.new(key, AES.MODE_CBC, iv).encrypt(padded)
    mac = hmac.new(key, iv + ciphertext, hashlib.sha256).digest()
    return base64.b64encode(iv + ciphertext + mac).decode("ascii")


def decrypt_credential(token_enc: str) -> dict[str, Any] | str:
    """解密：密文内容是 JSON 时返回 dict，否则返回原字符串。

    MAC 不匹配抛 OAuthCryptoError。
    """
    if AES is None:
        raise OAuthCryptoError("pycryptodome 未安装，无法解密凭证")
    try:
        raw = base64.b64decode(token_enc)
        if len(raw) < 16 + 32 + 16:
            raise ValueError("密文长度不足")
        iv, ciphertext, mac = raw[:16], raw[16:-32], raw[-32:]
        key = _derive_key()
        expected = hmac.new(key, iv + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected):
            raise OAuthCryptoError("MAC 校验失败（密钥变更或密文被篡改）")
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded = cipher.decrypt(ciphertext)
        pad_len = padded[-1]
        if pad_len < 1 or pad_len > 16:
            raise ValueError("PKCS#7 填充非法")
        plain = padded[:-pad_len].decode("utf-8")
        try:
            return json.loads(plain)
        except (ValueError, TypeError):
            return plain
    except OAuthCryptoError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise OAuthCryptoError(f"凭证解密失败: {exc}") from exc


def new_state_token() -> str:
    """OAuth state 一次性防 CSRF 令牌（32 位 hex）。"""
    return uuid.uuid4().hex + uuid.uuid4().hex[:16]


__all__ = [
    "OAuthCryptoError",
    "decrypt_credential",
    "encrypt_credential",
    "new_state_token",
]
