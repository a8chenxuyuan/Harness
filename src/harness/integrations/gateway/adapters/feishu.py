"""飞书（Lark）开放平台 Webhook channel（Phase 12 - FeishuAdapter）。

壳实现——只处理：
  - challenge 校验（X-Lark-Signature + challenge 参数）
  - 用 HTTP 回调事件队列做 receive
  - 用 tenant_access_token → POST im/v1/messages 做 send

**关键设计**：
  - config 缺失时构造函数仍能跑，但所有公有方法都会抛 ConfigurationError
  - server 启动时会检测 ``FeishuAdapter.ready_for_use``，False 就跳过注册

真正的飞书 server 回调入口（HTTP POST）需要 server 层额外路由；本 adapter
通过 :meth:`enqueue_event` 接收外部 HTTP 入口投递的事件。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

from ..channel import ChannelAdapter, RawMessage, SendResult

log = logging.getLogger(__name__)


class ConfigurationError(RuntimeError):
    """channel 配置缺失时抛出的运行时错误。

    server 层捕获此异常后会跳过该 adapter 的注册，而不是让整个进程崩掉。
    """


@dataclass
class FeishuConfig:
    """飞书配置字段。"""

    app_id: str
    app_secret: str
    verify_token: str | None = None
    encrypt_key: str | None = None


class FeishuAdapter(ChannelAdapter):
    """飞书 Open Platform Webhook 适配器（壳）。

    channel_name = "feishu"。
    """

    channel_name: str = "feishu"

    # ------------------------------------------------------------------
    # ready 检查
    # ------------------------------------------------------------------

    @property
    def ready_for_use(self) -> bool:
        """配置是否齐全（app_id + app_secret 都有）。

        Returns:
            True 时 server 可以安全地把它注册进 router。
        """
        cfg = self.config
        return bool(cfg.get("app_id") and cfg.get("app_secret"))

    # ------------------------------------------------------------------
    # receive：事件队列
    # ------------------------------------------------------------------

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        # 缓存 tenant_access_token
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def enqueue_event(self, event: dict[str, Any]) -> None:
        """把一个飞书事件（来自 HTTP 回调）投入 receive 队列。

        Args:
            event: 飞书开放平台事件 payload（包含 event / event_type 等）。
        """
        self._event_queue.put_nowait(event)

    async def receive(self) -> AsyncIterator[RawMessage]:
        """持续从事件队列产飞书消息。

        只处理 ``im.message.receive_v1`` 事件类型，其他事件跳过。

        Yields:
            RawMessage。channel_user_id 取 ``sender.sender_id.open_id``。
        """
        if not self.ready_for_use:
            raise ConfigurationError(
                "FeishuAdapter 未配置 app_id/app_secret，无法 receive"
            )

        while True:
            event = await self._event_queue.get()
            try:
                raw = event.get("event", event) or {}
                # 只关心文本消息
                msg = raw.get("message", {})
                msg_type = msg.get("message_type")
                if msg_type != "text":
                    continue
                content = msg.get("content", "{}")
                try:
                    text = json.loads(content).get("text", "")
                except (json.JSONDecodeError, AttributeError):
                    text = str(content)

                sender = raw.get("sender", {})
                open_id = sender.get("sender_id", {}).get("open_id", "")

                yield RawMessage(
                    channel="feishu",
                    channel_user_id=open_id,
                    content=text,
                    raw=event,
                )
            except Exception:  # noqa: BLE001
                log.warning("FeishuAdapter.receive 跳过一个事件", exc_info=True)

    # ------------------------------------------------------------------
    # send
    # ------------------------------------------------------------------

    async def send(self, message: str, user_id: str, **kwargs: Any) -> SendResult:
        """POST 到飞书 open-apis im/v1/messages。

        Args:
            message: 文本内容。
            user_id: 接收方 open_id。
            **kwargs: 可覆盖 msg_type（默认 "text"）。

        Returns:
            SendResult。
        """
        if not self.ready_for_use:
            return SendResult(
                ok=False,
                error="FeishuAdapter 未配置 app_id/app_secret",
            )

        try:
            token = await self._get_tenant_token()
        except Exception as exc:  # noqa: BLE001
            log.error("FeishuAdapter._get_tenant_token 失败: %s", exc)
            return SendResult(ok=False, error=f"tenant token error: {exc}")

        msg_type = kwargs.get("msg_type", "text")
        payload = {
            "receive_id_type": "open_id",
            "receive_id": user_id,
            "msg_type": msg_type,
            "content": json.dumps({"text": message}, ensure_ascii=False),
        }

        try:
            import httpx  # 可选依赖
        except ImportError:
            return SendResult(
                ok=False,
                error="httpx 未安装，FeishuAdapter.send 无法调用远端",
            )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://open.feishu.cn/open-apis/im/v1/messages",
                    params={"receive_id_type": "open_id"},
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
                body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                if resp.status_code == 200 and body.get("code") == 0:
                    return SendResult(
                        ok=True,
                        message_id=body.get("data", {}).get("message_id"),
                    )
                log.warning("FeishuAdapter.send 失败: %s %s", resp.status_code, body)
                return SendResult(
                    ok=False,
                    error=f"http={resp.status_code} code={body.get('code')} msg={body.get('msg')}",
                )
        except Exception as exc:  # noqa: BLE001
            log.exception("FeishuAdapter.send 异常")
            return SendResult(ok=False, error=str(exc))

    # ------------------------------------------------------------------
    # 飞书签名 / challenge 工具
    # ------------------------------------------------------------------

    def verify_signature(
        self, timestamp: str, nonce: str, body: bytes, signature: str
    ) -> bool:
        """X-Lark-Signature 验证。

        Args:
            timestamp: 请求头 X-Lark-Request-Timestamp。
            nonce: 请求头 X-Lark-Request-Nonce。
            body: 原始请求体字节。
            signature: 请求头 X-Lark-Signature。

        Returns:
            True 表示签名匹配。
        """
        cfg = self.config
        verify_token = cfg.get("verify_token") or ""
        sign_base = f"{timestamp}{nonce}{verify_token}{body.decode('utf-8', errors='replace')}"
        expected = hmac.new(
            sign_base.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def build_challenge_response(challenge: str) -> dict[str, str]:
        """把 challenge 参数原样返回给飞书。

        Args:
            challenge: query/body 里的 challenge 字符串。

        Returns:
            {"challenge": "..."} dict。
        """
        return {"challenge": challenge}

    # ------------------------------------------------------------------
    # tenant_access_token 缓存
    # ------------------------------------------------------------------

    async def _get_tenant_token(self) -> str:
        """获取/刷新 tenant_access_token。"""
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        try:
            import httpx
        except ImportError as exc:
            raise ConfigurationError("httpx 未安装") from exc

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self.config["app_id"],
                    "app_secret": self.config["app_secret"],
                },
            )
            body = resp.json()
            if resp.status_code != 200 or body.get("code") != 0:
                raise RuntimeError(f"token fetch failed: {body}")
            self._token = body["tenant_access_token"]
            self._token_expires_at = time.time() + int(body.get("expire", 7200))
            return self._token  # type: ignore[return-value]
