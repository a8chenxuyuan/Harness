"""企业微信自建应用回调 Controller（W4-CHAN-02A）。

暴露一个路由 /channels/wecom 同时处理：
  - GET  URL 验证：msg_signature + timestamp + nonce + echostr → 解密返回 echostr 明文
  - POST 业务推送：msg_signature + timestamp + nonce + <xml><Encrypt>...

POST 处理：
  1. 解析 query 里的签名参数
  2. 从 XML body 取 <Encrypt>
  3. adapter.verify_and_decrypt() 验签 + 解密
  4. adapter.enqueue_event() 投队供 receive() 消费
  5. 同步返回 "success"（企微不会重复投递）

回调 5 秒超时——这里不做任何业务处理，只验签解密投队，保证瞬时响应。
业务消费由 GatewayRouter 的 receive/send 主循环完成（与飞书/其他渠道共享）。

adapter 实例来源：从 app.state.wecom_adapter 取（lifespan 里创建），
fallback 到 env 读取默认配置。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from xml.etree import ElementTree as ET

from harness.platform.api.exceptions import BizError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/channels/wecom", tags=["channels-wecom"])


def _get_adapter(app: Any) -> Any:
    """从 app.state 取 WeComAdapter；没有就抛 503。"""
    adapter = getattr(app.state, "wecom_adapter", None)
    if adapter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WeComAdapter 未注册，配置 corp_id/token/encoding_aes_key 后重试",
        )
    return adapter


async def _extract_encrypt_xml(body_bytes: bytes) -> str:
    """从 POST body 解 XML 取 <Encrypt> 字段。

    Returns:
        <Encrypt> 的文本内容。
    Raises:
        HTTPException(400): XML 格式错误或缺失 Encrypt。
    """
    try:
        root = ET.fromstring(body_bytes)
    except ET.ParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"XML 解析失败: {exc}",
        )
    encrypt_el = root.find("Encrypt")
    if encrypt_el is None or not (encrypt_el.text or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="XML 中缺少 <Encrypt> 字段",
        )
    return encrypt_el.text.strip()  # type: ignore[union-attr]


@router.get("", response_class=PlainTextResponse)
async def wecom_verify_url(
    msg_signature: str,
    timestamp: str,
    nonce: str,
    echostr: str,
    request: Request,
) -> PlainTextResponse:
    """企微后台配置回调 URL 时的一次性验证。

    步骤：
      1. 用 token + timestamp + nonce + echostr 计算 SHA1，与 msg_signature 比对
      2. 用 AES-256-CBC 解密 echostr 得到明文
      3. 把明文原样（无引号无换行）作为 HTTP body 返回
    """
    adapter = _get_adapter(request.app)
    try:
        plaintext = adapter.verify_and_decrypt(msg_signature, timestamp, nonce, echostr)
    except Exception as exc:  # noqa: BLE001
        log.warning("企微 URL 验证失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"验证失败: {exc}",
        )
    # 必须 PlainTextResponse，不能 JSON；企微精确比对 HTTP body
    return PlainTextResponse(content=plaintext, status_code=200)


@router.post("", response_class=PlainTextResponse)
async def wecom_receive_event(
    msg_signature: str,
    timestamp: str,
    nonce: str,
    request: Request,
) -> PlainTextResponse:
    """企微推送业务事件（消息/事件）。

    验签解密 → 投队 → 返回 "success"。
    同步返回不能超过 5 秒；此处不做业务处理。
    """
    adapter = _get_adapter(request.app)
    body_bytes = await request.body()
    encrypt = await _extract_encrypt_xml(body_bytes)

    try:
        plain_xml = adapter.verify_and_decrypt(msg_signature, timestamp, nonce, encrypt)
    except Exception as exc:  # noqa: BLE001
        log.warning("企微消息验签/解密失败: %s", exc)
        # 验签失败说明不是企微来源，返回非 success 让企微按自身规则重试
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"验签/解密失败: {exc}",
        )

    adapter.enqueue_event(plain_xml)
    # 企微要求 POST 响应体等于空字符串或 "success"（回调模式不要求被动回复）
    return PlainTextResponse(content="success", status_code=200)


__all__ = ["router"]
