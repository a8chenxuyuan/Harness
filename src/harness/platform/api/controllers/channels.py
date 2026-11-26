"""渠道接入：飞书机器人 Webhook（Phase 23）。

流程：
    1. 未配置 app_id / app_secret → 503（渠道未启用）
    2. verify_token 不匹配 → 403
    3. ``url_verification`` 事件 → 原样返回 challenge
    4. 普通消息事件 → 取 text，走 coordinator 模式跑一次 Agent
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/channels", tags=["channels"])

log = logging.getLogger(__name__)


def _feishu_config() -> dict[str, Any]:
    """读取飞书配置。

    优先 env ``HARNESS_GATEWAY_FEISHU``（JSON，便于容器零配置文件部署，
    与 HARNESS_DATABASE_URL / HARNESS_DEV_MODE 的显式 env 约定一致），
    其次回落到 ``Settings().gateway.feishu``。
    """
    raw = os.environ.get("HARNESS_GATEWAY_FEISHU", "")
    if raw:
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            log.warning("channels: HARNESS_GATEWAY_FEISHU 不是合法 JSON，已忽略")
            return {}
    from harness.common.config.settings import Settings

    return dict(Settings().gateway.feishu)


@router.post("/feishu/webhook")
async def feishu_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """飞书事件回调入口（无用户态，按租户 ``feishu`` 记账）。"""
    config = _feishu_config()
    if not (config.get("app_id") and config.get("app_secret")):
        raise HTTPException(status_code=503, detail="feishu channel not configured")

    expected = str(config.get("verify_token") or "")
    token = str(payload.get("token") or payload.get("header", {}).get("token") or "")
    if expected and token != expected:
        raise HTTPException(status_code=403, detail="invalid verify token")

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    text = _extract_text(payload)
    if not text:
        raise HTTPException(status_code=400, detail="empty message text")

    from harness.platform.service.agent_service import AgentService

    result = await AgentService().run(
        goal=text,
        mode="coordinator",
        conversation_id=str(payload.get("event", {}).get("event_id") or ""),
        user_id="feishu-bot",
        tenant_id="feishu",
    )
    return {"code": 0, "message": "ok", "data": result}


def _extract_text(payload: dict[str, Any]) -> str:
    """从飞书消息事件里提取纯文本（content 是 JSON 字符串）。"""
    content = (
        payload.get("event", {}).get("message", {}).get("content", "")
    )
    if isinstance(content, str) and content:
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict) and isinstance(parsed.get("text"), str):
                return parsed["text"].strip()
        except json.JSONDecodeError:
            return content.strip()
    return ""


__all__ = ["router"]
