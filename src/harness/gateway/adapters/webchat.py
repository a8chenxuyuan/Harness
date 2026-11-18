"""WebChatAdapter：基于 FastAPI WebSocket 的浏览器聊天 channel（Phase 12）。

WebChatAdapter 本身只负责 "一条 ws 连接就是一个 user"——它不存储 ws 引用，
真正的 ws.send_text 需要 server 层把具体 WebSocket 对象传给 send()。
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from ..channel import ChannelAdapter, RawMessage, SendResult

log = logging.getLogger(__name__)


class WebChatAdapter(ChannelAdapter):
    """浏览器 WebSocket 适配器。

    channel_name = "webchat"。每条 WebSocket 连接视为一个独立用户，
    用 ws 的 ``query_params.get("user_id")`` 作为 ``channel_user_id``，
    没传则用 ``client.host + client.port`` 合成。

    Attributes:
        _active_ws: 存储中的 WebSocket 实例（通过 :meth:`bind_ws` 注入）。
    """

    channel_name: str = "webchat"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        # user_id -> WebSocket 实例
        self._active_ws: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 注入 WebSocket
    # ------------------------------------------------------------------

    def bind_ws(self, user_id: str, ws: Any) -> None:
        """把一条新 WebSocket 与 user_id 绑定。

        Args:
            user_id: channel_user_id。
            ws: FastAPI 的 WebSocket 对象。
        """
        self._active_ws[user_id] = ws

    def unbind_ws(self, user_id: str) -> None:
        """移除一条绑定（连接关闭时调用）。"""
        self._active_ws.pop(user_id, None)

    # ------------------------------------------------------------------
    # ChannelAdapter 实现
    # ------------------------------------------------------------------

    async def receive(self) -> AsyncIterator[RawMessage]:
        """接收 WebSocket 消息。

        WebSocket 消息由 server 层主动 ``receive_text()``，所以本方法
        依赖 server 通过 :meth:`enqueue` 投递消息进来——真正的异步
        迭代在 server 的 WebSocket endpoint 里完成。

        这里提供一个 stub，让类型系统不报错；实际使用建议直接走
        server 的 ws endpoint 而不是调用本方法。
        """
        import asyncio

        log.debug("WebChatAdapter.receive() 进入 stub 等待——"
                  "推荐在 server WebSocket endpoint 里直接循环 receive")
        # 挂起永不返回，真正的消息接收逻辑在 GatewayServer 内部实现
        while True:
            await asyncio.sleep(3600)

    async def send(self, message: str, user_id: str, **kwargs: Any) -> SendResult:
        """向指定 user_id 的 WebSocket 发送消息。

        Args:
            message: 文本内容（支持纯文本或 JSON 字符串）。
            user_id: WebSocket 绑定的 user_id。
            **kwargs: 忽略（WebChat 不需要额外参数）。

        Returns:
            SendResult。
        """
        ws = self._active_ws.get(user_id)
        if ws is None:
            return SendResult(ok=False, error=f"no active ws for user {user_id}")

        try:
            # 纯文本直接发
            await ws.send_text(message)
            return SendResult(ok=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("WebChatAdapter.send 失败 user=%s: %s", user_id, exc)
            # 移除失效 ws
            self._active_ws.pop(user_id, None)
            return SendResult(ok=False, error=str(exc))


# ---------------------------------------------------------------------------
# 小工具：FastAPI WebSocket → 辅助函数
# ---------------------------------------------------------------------------


async def parse_ws_message(raw_text: str, channel_user_id: str) -> RawMessage:
    """把一条 WebSocket JSON 文本解析成 RawMessage。

    约定消息格式::

        {"content": "用户输入"}  # 或纯字符串

    JSON 解析失败时把整段文本当作 content。

    Args:
        raw_text: ws.receive_text() 得到的原始文本。
        channel_user_id: 本连接绑定的 user_id。

    Returns:
        RawMessage（channel 固定为 "webchat"）。
    """
    content = raw_text
    raw: dict[str, Any] = {}

    try:
        obj = json.loads(raw_text)
        if isinstance(obj, dict):
            content = str(obj.get("content", ""))
            raw = obj
        else:
            content = str(obj)
    except json.JSONDecodeError:
        # 不是 JSON，原样当 content
        pass

    return RawMessage(
        channel="webchat",
        channel_user_id=channel_user_id,
        content=content,
        raw=raw,
    )
