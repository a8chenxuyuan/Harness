"""Gateway 核心数据结构与 ChannelAdapter 抽象基类（Phase 12）。

本模块只定义协议层——不涉及任何具体 channel 的实现，也不依赖 FastAPI
或 httpx，保证被 import 时永远不会因缺少可选依赖而失败。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass(frozen=True)
class RawMessage:
    """从某个 channel 收到的原始消息。

    Attributes:
        channel: 来源 channel 标识（如 "webchat" / "feishu"）。
        channel_user_id: 原 channel 里的用户 id（如飞书的 open_id）。
        content: 文本内容。
        raw: channel 原始 payload（dict），方便下游扩展解析。
    """

    channel: str
    channel_user_id: str
    content: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SendResult:
    """向 channel 发送消息的结果。

    Attributes:
        ok: True 表示发送成功。
        message_id: 远端返回的消息 id（可选）。
        error: 失败时的错误文本。
    """

    ok: bool
    message_id: str | None = None
    error: str | None = None


class ChannelAdapter(ABC):
    """单个通信渠道的适配基类。

    子类需要实现：
      - :attr:`channel_name` —— 唯一标识
      - :meth:`receive` —— 异步迭代器，持续产 RawMessage
      - :meth:`send` —— 向指定 user_id 发文本

    构造时传入 config dict；具体字段由子类自己解释。
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """初始化。

        Args:
            config: channel 私有配置。子类可以从中取 app_id、token 等。
                    基类本身不使用。
        """
        self.config: dict[str, Any] = dict(config) if config else {}

    # ------------------------------------------------------------------
    # 子类必须实现
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """唯一 channel 标识字符串。"""
        ...

    @abstractmethod
    async def receive(self) -> AsyncIterator[RawMessage]:
        """持续接收消息。

        通常是一个 ``async for`` 能直接消费的异步生成器，
        内部需要阻塞等待（WebSocket 消息 / HTTP 回调队列 / stdin 等）。

        Yields:
            RawMessage 实例。
        """
        ...

    @abstractmethod
    async def send(self, message: str, user_id: str, **kwargs: Any) -> SendResult:
        """发送一条文本消息。

        Args:
            message: 文本内容。
            user_id: channel 用户标识。
            **kwargs: 扩展参数（如飞书的 msg_type）。

        Returns:
            SendResult 实例，ok=True 表示成功。
        """
        ...
