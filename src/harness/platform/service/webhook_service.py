"""Webhook 服务 — 订阅 CRUD、HMAC 签名与带重试的投递器（W4-CHAN-03）。

签名协议：
    sig = HMAC-SHA256(secret, "{timestamp}.{raw_body}")
    Header：X-Harness-Signature: v1=<sig> / X-Harness-Timestamp / X-Harness-Event

投递策略：
    最多尝试 4 次（首次 + 3 次重试），重试间隔 0.5s / 2s / 8s 指数退避；
    单次请求超时 10s；2xx 即视为成功，落一条最终态投递记录。

可测试性：
    ``run_delivery`` 的 ``client`` 参数允许注入 httpx.AsyncClient
    （配合 MockTransport），测试无需真实网络；重试间隔可通过
    覆写模块常量 ``RETRY_DELAYS`` 归零加速。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from harness.platform.api.exceptions import BizError
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.entity.webhook import WebhookDelivery, WebhookSubscription
from harness.platform.repository.webhook_repository import WebhookRepository

# 重试间隔（秒）：首次失败后依次等待；末次尝试后不再等待
RETRY_DELAYS: list[float] = [0.5, 2.0, 8.0]
# 最多尝试次数 = 首次 + 全部重试
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
# 单次 HTTP 请求超时（秒）
REQUEST_TIMEOUT = 10.0
# 请求/响应体留痕截断长度（字符）
REQUEST_BODY_MAX = 4000
RESPONSE_BODY_MAX = 2000
# 签名密钥长度（hex 字符数）
SECRET_LEN = 48

# 允许的回调协议
_ALLOWED_SCHEMES = ("http://", "https://")


def sign_payload(secret: str, timestamp: str, raw_body: str) -> str:
    """按协议计算签名（v1= 前缀）。

    Args:
        secret: 订阅签名密钥。
        timestamp: Unix 秒级时间戳字符串。
        raw_body: 原始请求体字符串。

    Returns:
        形如 ``v1=<hex>`` 的签名值。
    """
    message = f"{timestamp}.{raw_body}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"v1={digest}"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_event_types(raw: str) -> list[str]:
    """订阅表里的 event_types JSON 数组 → 列表。"""
    try:
        value = json.loads(raw)
        return [str(v) for v in value] if isinstance(value, list) else []
    except Exception:  # noqa: BLE001 — 脏数据按"全部事件"处理
        return []


def _matches(subscription: WebhookSubscription, event_type: str) -> bool:
    """订阅是否关心该事件类型（空列表 = 全部）。"""
    wanted = _parse_event_types(subscription.event_types)
    return not wanted or event_type in wanted


# ---------------------------------------------------------------------------
# 订阅 CRUD
# ---------------------------------------------------------------------------

async def create_webhook(
    db,
    *,
    user: UserInfo,
    name: str,
    url: str,
    event_types: list[str] | None = None,
) -> dict[str, Any]:
    """登记一个新 Webhook 订阅。

    Args:
        db: AsyncSession。
        user: 当前用户（订阅归属其租户）。
        name: 展示名称。
        url: 回调 URL（仅支持 http/https）。
        event_types: 关心的事件类型；None/空 = 全部事件。

    Returns:
        {"webhook": 脱敏记录 dict, "secret": 明文密钥（仅此一次）}。
    """
    if not name.strip():
        raise BizError(422, "name 不能为空")
    if not url.startswith(_ALLOWED_SCHEMES):
        raise BizError(422, "url 仅支持 http/https")

    # 校验事件类型合法性（EventType 枚举成员）
    from harness.common.event.types import EventType

    wanted = list(dict.fromkeys(event_types or []))  # 去重保序
    for et in wanted:
        if et not in {e.value for e in EventType}:
            raise BizError(422, f"未知事件类型: {et}")

    secret_plain = secrets.token_hex(SECRET_LEN // 2)
    record = WebhookSubscription(
        id=str(uuid.uuid4()),
        tenant_id=user.tenant_id,
        name=name.strip(),
        url=url.strip(),
        secret=secret_plain,
        event_types=json.dumps(wanted, ensure_ascii=False),
        created_by=user.user_id,
    )
    await WebhookRepository(db).add_subscription(record)
    return {"webhook": _sub_to_dict(record), "secret": secret_plain}


async def list_webhooks(db, user: UserInfo) -> list[dict[str, Any]]:
    """列出租户下全部订阅（secret 只展示前 8 位前缀）。"""
    records = await WebhookRepository(db).list_subscriptions(user.tenant_id)
    return [_sub_to_dict(r) for r in records]


async def delete_webhook(db, user: UserInfo, webhook_id: str) -> bool:
    """删除一个订阅（连同其投递记录）。

    Returns:
        True=已删除；False=不存在。
    Raises:
        BizError(403): 订阅不属于当前租户。
    """
    repo = WebhookRepository(db)
    record = await repo.get_subscription(webhook_id)
    if record is None:
        return False
    if record.tenant_id != user.tenant_id:
        raise BizError(403, "无权操作其他租户的 Webhook")
    return await repo.delete_subscription(webhook_id)


async def get_webhook_deliveries(
    db, user: UserInfo, webhook_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    """查一个订阅的投递记录（同租户校验，最新在前）。"""
    record = await _get_owned(db, user, webhook_id)
    rows = await WebhookRepository(db).list_deliveries(record.id, limit=limit)
    return [_delivery_to_dict(r) for r in rows]


async def send_test_event(
    db,
    user: UserInfo,
    webhook_id: str,
    *,
    client: Any = None,
) -> dict[str, Any]:
    """向订阅 URL 发一条测试事件，返回投递结果。"""
    record = await _get_owned(db, user, webhook_id)
    payload = {
        "source": "harness",
        "message": "webhook test",
        "webhook_id": record.id,
    }
    delivery = await run_delivery(
        db, record, "webhook.test", payload, client=client
    )
    return _delivery_to_dict(delivery)


# ---------------------------------------------------------------------------
# 投递器（REST /test 与调度器共用）
# ---------------------------------------------------------------------------

async def run_delivery(
    db,
    subscription: WebhookSubscription,
    event_type: str,
    payload: dict[str, Any],
    *,
    client: Any = None,
) -> WebhookDelivery:
    """带重试地把一条事件 POST 到订阅 URL，并落投递记录。

    Args:
        db: AsyncSession（写投递记录）。
        subscription: 订阅记录（取 url / secret）。
        event_type: 事件类型字符串。
        payload: 事件附加数据。
        client: 可注入的 httpx.AsyncClient；None=内部新建。

    Returns:
        WebhookDelivery 记录（已落库）。
    """
    body_obj = {
        "event_type": event_type,
        "session_id": payload.get("session_id"),
        "timestamp": _now_utc().isoformat(),
        "data": payload,
    }
    raw_body = json.dumps(body_obj, ensure_ascii=False, default=str)

    status_code: int | None = None
    response_text = ""
    ok = False
    started = time.monotonic()
    attempts = 0

    owns_client = client is None
    http = client if client is not None else _new_client()
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            attempts = attempt
            ts = str(int(time.time()))
            headers = {
                "Content-Type": "application/json",
                "X-Harness-Signature": sign_payload(subscription.secret, ts, raw_body),
                "X-Harness-Timestamp": ts,
                "X-Harness-Event": event_type,
            }
            try:
                resp = await http.post(
                    subscription.url, content=raw_body, headers=headers
                )
                status_code = resp.status_code
                response_text = (resp.text or "")[:RESPONSE_BODY_MAX]
                if 200 <= status_code < 300:
                    ok = True
                    break
            except Exception as exc:  # noqa: BLE001 — 网络/超时异常计入重试
                status_code = None
                response_text = f"{type(exc).__name__}: {exc}"[:RESPONSE_BODY_MAX]
            if attempt <= len(RETRY_DELAYS):
                await asyncio.sleep(RETRY_DELAYS[attempt - 1])
    finally:
        if owns_client:
            await http.aclose()

    duration_ms = int((time.monotonic() - started) * 1000)
    record = WebhookDelivery(
        id=str(uuid.uuid4()),
        subscription_id=subscription.id,
        event_type=event_type,
        status="success" if ok else "failed",
        status_code=status_code,
        attempts=attempts,
        duration_ms=duration_ms,
        request_body=raw_body[:REQUEST_BODY_MAX],
        response_body=response_text,
    )
    await WebhookRepository(db).add_delivery(record)
    return record


def _new_client():
    """构造默认投递客户端（延迟 import，httpx 缺失时给出可读报错）。"""
    try:
        import httpx
    except Exception as exc:  # noqa: BLE001
        raise BizError(500, "httpx 未安装，无法投递 Webhook") from exc
    return httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True)


# ---------------------------------------------------------------------------
# 记录 → dict
# ---------------------------------------------------------------------------

async def _get_owned(db, user: UserInfo, webhook_id: str) -> WebhookSubscription:
    """取订阅并做同租户校验；不存在 404、跨租户 403。"""
    record = await WebhookRepository(db).get_subscription(webhook_id)
    if record is None:
        raise BizError(404, f"webhook {webhook_id} not found")
    if record.tenant_id != user.tenant_id:
        raise BizError(403, "无权操作其他租户的 Webhook")
    return record


def _sub_to_dict(record: WebhookSubscription) -> dict[str, Any]:
    """订阅记录转响应 dict：secret 只露出前 8 位前缀。"""
    return {
        "id": record.id,
        "name": record.name,
        "url": record.url,
        "secret_prefix": record.secret[:8],
        "event_types": _parse_event_types(record.event_types),
        "is_active": record.is_active,
        "created_by": record.created_by,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _delivery_to_dict(record: WebhookDelivery) -> dict[str, Any]:
    """投递记录转响应 dict（request_body 不回传，前端看响应即可）。"""
    return {
        "id": record.id,
        "subscription_id": record.subscription_id,
        "event_type": record.event_type,
        "status": record.status,
        "status_code": record.status_code,
        "attempts": record.attempts,
        "duration_ms": record.duration_ms,
        "response_body": record.response_body,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


__all__ = [
    "RETRY_DELAYS",
    "MAX_ATTEMPTS",
    "sign_payload",
    "create_webhook",
    "list_webhooks",
    "delete_webhook",
    "get_webhook_deliveries",
    "send_test_event",
    "run_delivery",
]
