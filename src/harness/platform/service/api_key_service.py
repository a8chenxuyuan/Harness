"""API Key 服务 — 机器调用凭据的签发 / 查询 / 吊销（W4-API-01）。

key 生成规则：``hk_`` + ``secrets.token_hex(16)``（32 位 hex）。
只落 SHA-256 哈希；明文仅在创建响应里出现一次，服务端不留副本。

鉴权链（deps.get_current_user 按前缀分流）：
    Bearer hk_... → sha256 → ApiKeyRepository.get_by_hash
    → 校验 is_active / expires_at → 刷新 last_used_at → UserInfo(role="machine")
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from harness.platform.api.exceptions import BizError
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.entity.api_key import ApiKey
from harness.platform.repository.api_key_repository import ApiKeyRepository

# key 前缀：鉴权分流依据，也是外部程序识别凭据类型的标志
API_KEY_PREFIX = "hk_"
# 明文展示用前缀长度（hk_ + 8 位 hex）
PREFIX_DISPLAY_LEN = 12


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _hash_key(plaintext: str) -> str:
    """API key 的 SHA-256 哈希（不落明文）。"""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    """SQLite 取回的 datetime 可能无时区，统一按 UTC 处理。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ---------------------------------------------------------------------------
# 签发 / 查询 / 吊销
# ---------------------------------------------------------------------------

async def create_api_key(
    db,
    *,
    user: UserInfo,
    name: str,
    expires_in_days: int | None = None,
) -> dict[str, Any]:
    """签发一个新 API Key。

    Args:
        db: AsyncSession（由 Controller 注入）。
        user: 当前登录用户（key 归属其租户）。
        name: 展示名称。
        expires_in_days: 有效期天数；None=永不过期。

    Returns:
        {"key": 脱敏记录 dict, "plaintext": 明文 key（仅此一次）}。
    """
    if not name.strip():
        raise BizError(422, "name 不能为空")

    plaintext = API_KEY_PREFIX + secrets.token_hex(16)
    record = ApiKey(
        id=str(uuid.uuid4()),
        name=name.strip(),
        key_prefix=plaintext[:PREFIX_DISPLAY_LEN],
        key_hash=_hash_key(plaintext),
        tenant_id=user.tenant_id,
        created_by=user.user_id,
        expires_at=(
            _now_utc() + timedelta(days=expires_in_days) if expires_in_days else None
        ),
    )
    repo = ApiKeyRepository(db)
    await repo.add(record)

    return {"key": _record_to_dict(record), "plaintext": plaintext}


async def list_api_keys(db, user: UserInfo) -> list[dict[str, Any]]:
    """列出租户下全部 API Key（脱敏，不含哈希与明文）。"""
    records = await ApiKeyRepository(db).list_for_tenant(user.tenant_id)
    return [_record_to_dict(r) for r in records]


async def revoke_api_key(db, user: UserInfo, key_id: str) -> bool:
    """吊销一个 API Key（同租户校验）。

    Returns:
        True=确实吊销；False=key 不存在。
    Raises:
        BizError(403): key 不属于当前用户租户。
    """
    repo = ApiKeyRepository(db)
    record = await repo.get(key_id)
    if record is None:
        return False
    if record.tenant_id != user.tenant_id:
        raise BizError(403, "无权操作其他租户的 API Key")
    return await repo.revoke(key_id)


# ---------------------------------------------------------------------------
# 鉴权入口（deps.get_current_user 调用）
# ---------------------------------------------------------------------------

async def authenticate_key(db, token: str) -> UserInfo | None:
    """校验 Bearer 携带的 API key 明文。

    校验链：哈希查表 → is_active → 未过期。
    成功返回 UserInfo（role="machine"，user_id=key id）并刷新 last_used_at；
    任何一步失败返回 None（调用方统一转 401）。
    """
    if not token.startswith(API_KEY_PREFIX):
        return None

    record = await ApiKeyRepository(db).get_by_hash(_hash_key(token))
    if record is None or not record.is_active:
        return None
    if record.expires_at is not None and _as_utc(record.expires_at) <= _now_utc():
        return None

    await ApiKeyRepository(db).touch_last_used(record)
    return UserInfo(user_id=record.id, tenant_id=record.tenant_id, role="machine")


# ---------------------------------------------------------------------------
# 记录 → 脱敏 dict
# ---------------------------------------------------------------------------

def _record_to_dict(record: ApiKey) -> dict[str, Any]:
    """ApiKey 记录转响应 dict：绝不外泄 key_hash。"""
    return {
        "id": record.id,
        "name": record.name,
        "key_prefix": record.key_prefix,
        "tenant_id": record.tenant_id,
        "created_by": record.created_by,
        "scopes": record.scopes,
        "is_active": record.is_active,
        "last_used_at": record.last_used_at.isoformat() if record.last_used_at else None,
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


__all__ = [
    "API_KEY_PREFIX",
    "create_api_key",
    "list_api_keys",
    "revoke_api_key",
    "authenticate_key",
]
