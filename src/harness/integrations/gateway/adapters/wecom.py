"""企业微信自建应用 ChannelAdapter（W4-CHAN-02A）。

与飞书 adapter 同构：
  - 事件队列（receive() 迭代器）+ enqueue_event()（controller 投递）
  - access_token 自动续期（corp_id + secret → gettoken）
  - send() 调 https://qyapi.weixin.qq.com/cgi-bin/message/send

被动回复（同步响应）另开一个入口：
  build_passive_reply(message, to_user) → 加密 XML 字符串
  供 /channels/wecom 回调 controller 在收到消息后 5 秒内返回。

**配置字段**（来自 channel_apps 表或 env）：
  corp_id / agent_id / secret / token / encoding_aes_key
  至少 corp_id + secret + agent_id 齐全才能 send；
  receive 还需要 token + encoding_aes_key（解消息体）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import xml.etree.ElementTree as ET
from typing import Any, AsyncIterator

from ..channel import ChannelAdapter, RawMessage, SendResult
from ..wecom_crypto import CryptoError, WeComCrypto, build_passive_reply_xml

log = logging.getLogger(__name__)


class ConfigurationError(RuntimeError):
    """企微配置缺失时抛出；server 层捕获后跳过注册。"""


class WeComAdapter(ChannelAdapter):
    """企业微信自建应用适配器。

    channel_name = "wecom"。
    """

    channel_name: str = "wecom"

    BASE_URL = "https://qyapi.weixin.qq.com/cgi-bin"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        # access_token 缓存
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        # 延迟构造 WeComCrypto（可能 token/aes_key 未配置）
        self._crypto: WeComCrypto | None = None

    # ------------------------------------------------------------------
    # ready 检查
    # ------------------------------------------------------------------

    @property
    def ready_for_send(self) -> bool:
        """发送需要 corp_id + secret + agent_id。"""
        cfg = self.config
        return bool(cfg.get("corp_id") and cfg.get("secret") and cfg.get("agent_id"))

    @property
    def ready_for_receive(self) -> bool:
        """接收需要 corp_id + token + encoding_aes_key（解消息体）。"""
        cfg = self.config
        return bool(
            cfg.get("corp_id")
            and cfg.get("token")
            and cfg.get("encoding_aes_key")
        )

    @property
    def ready_for_use(self) -> bool:
        """任意一侧 ready 就算可用。"""
        return self.ready_for_send or self.ready_for_receive

    def _get_crypto(self) -> WeComCrypto:
        """懒构造 WeComCrypto。"""
        if self._crypto is None:
            if not self.ready_for_receive:
                raise ConfigurationError(
                    "WeComAdapter 未配置 corp_id/token/encoding_aes_key，无法解密"
                )
            self._crypto = WeComCrypto(
                token=str(self.config["token"]),
                encoding_aes_key=str(self.config["encoding_aes_key"]),
                receive_id=str(self.config["corp_id"]),
            )
        return self._crypto

    # ------------------------------------------------------------------
    # receive：controller 解完 XML 后 enqueue，这里迭代
    # ------------------------------------------------------------------

    def enqueue_event(self, plain_xml: str) -> None:
        """controller 解密后的明文 XML 投入 receive 队列。

        Args:
            plain_xml: 企微明文消息 XML（包含 <FromUserName>/<Content> 等）。
        """
        self._event_queue.put_nowait({"xml": plain_xml})

    def verify_and_decrypt(
        self,
        msg_signature: str,
        timestamp: str,
        nonce: str,
        encrypt: str,
    ) -> str:
        """验签 + 解密；失败抛 CryptoError。"""
        crypto = self._get_crypto()
        if not crypto.verify_signature(msg_signature, timestamp, nonce, encrypt):
            raise CryptoError(f"msg_signature 校验失败: {msg_signature}")
        return crypto.decrypt(encrypt)

    async def receive(self) -> AsyncIterator[RawMessage]:
        """持续从队列产企微消息。

        只处理 MsgType=text；其他事件（event / image 等）跳过。
        Yields:
            RawMessage。channel_user_id 取 ``<FromUserName>``（企微 UserID）。
        """
        if not self.ready_for_receive:
            raise ConfigurationError(
                "WeComAdapter 未配置 corp_id/token/encoding_aes_key，无法 receive"
            )

        while True:
            event = await self._event_queue.get()
            try:
                plain_xml = event["xml"]
                root = ET.fromstring(plain_xml)
                msg_type = _xml_text(root, "MsgType")
                if msg_type != "text":
                    log.debug("WeComAdapter.receive 跳过 MsgType=%s", msg_type)
                    continue

                content = _xml_text(root, "Content") or ""
                from_user = _xml_text(root, "FromUserName") or ""
                agent_id = _xml_text(root, "AgentID") or str(self.config.get("agent_id", ""))
                yield RawMessage(
                    channel="wecom",
                    channel_user_id=from_user,
                    content=content,
                    raw={
                        "xml": plain_xml,
                        "agent_id": agent_id,
                    },
                )
            except Exception:  # noqa: BLE001
                log.warning("WeComAdapter.receive 跳过一个事件", exc_info=True)

    # ------------------------------------------------------------------
    # send（异步 API 调用）
    # ------------------------------------------------------------------

    async def send(self, message: str, user_id: str, **kwargs: Any) -> SendResult:
        """POST cgi-bin/message/send。

        Args:
            message: 文本内容（最长 2048 字节，企微会截断）。
            user_id: 接收方企微 UserID（多个用 ``|`` 分隔）。
        """
        if not self.ready_for_send:
            return SendResult(
                ok=False,
                error="WeComAdapter 未配置 corp_id/secret/agent_id",
            )

        try:
            token = await self._get_access_token()
        except Exception as exc:  # noqa: BLE001
            log.error("WeComAdapter._get_access_token 失败: %s", exc)
            return SendResult(ok=False, error=f"access_token error: {exc}")

        payload = {
            "touser": user_id,
            "msgtype": "text",
            "agentid": int(self.config["agent_id"]),
            "text": {"content": message},
            "safe": 0,
        }

        try:
            import httpx
        except ImportError:
            return SendResult(ok=False, error="httpx 未安装")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/message/send",
                    params={"access_token": token},
                    json=payload,
                )
                body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                if resp.status_code == 200 and body.get("errcode") == 0:
                    return SendResult(
                        ok=True,
                        message_id=str(body.get("msgid")) if body.get("msgid") else None,
                    )
                log.warning("WeComAdapter.send 失败: %s %s", resp.status_code, body)
                return SendResult(
                    ok=False,
                    error=f"http={resp.status_code} errcode={body.get('errcode')} errmsg={body.get('errmsg')}",
                )
        except Exception as exc:  # noqa: BLE001
            log.exception("WeComAdapter.send 异常")
            return SendResult(ok=False, error=str(exc))

    # ------------------------------------------------------------------
    # 被动回复（同步）
    # ------------------------------------------------------------------

    def build_passive_reply(self, plain_msg_xml: str) -> str:
        """把明文被动回复 XML 加密后返回可直接作为 HTTP 响应体的 XML 字符串。

        Args:
            plain_msg_xml: 被动回复的明文 XML（如
                ``<xml><Content><![CDATA[reply]]></Content><MsgType><![CDATA[text]]></MsgType><ToUserName>...</ToUserName><FromUserName>...</FromUserName><CreateTime>0</CreateTime></xml>``）

        Returns:
            加密后的完整 XML 字符串（含 Encrypt / MsgSignature / TimeStamp / Nonce）。
        """
        crypto = self._get_crypto()
        nonce = _random_nonce()
        timestamp = str(int(time.time()))
        parts = crypto.encrypt(plain_msg_xml, nonce, timestamp)
        return build_passive_reply_xml(parts)

    # ------------------------------------------------------------------
    # access_token 缓存
    # ------------------------------------------------------------------

    async def _get_access_token(self) -> str:
        """获取/刷新 access_token（提前 60s 刷新）。"""
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        try:
            import httpx
        except ImportError as exc:  # noqa: BLE001
            raise ConfigurationError("httpx 未安装") from exc

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.BASE_URL}/gettoken",
                params={
                    "corpid": self.config["corp_id"],
                    "corpsecret": self.config["secret"],
                },
            )
            body = resp.json()
            if resp.status_code != 200 or body.get("errcode") != 0:
                raise RuntimeError(f"gettoken failed: {body}")
            self._access_token = body["access_token"]
            self._token_expires_at = time.time() + int(body.get("expires_in", 7200))
            return self._access_token  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 模块级辅助
# ---------------------------------------------------------------------------

def _xml_text(root: ET.Element, tag: str) -> str | None:
    """取 XML 某 tag 的文本；不存在返回 None。"""
    el = root.find(tag)
    return (el.text or "") if el is not None else None


def _random_nonce() -> str:
    """被动回复签名用的 nonce（16 位 hex 足够）。"""
    import secrets
    return secrets.token_hex(8)


__all__ = ["WeComAdapter", "ConfigurationError"]
