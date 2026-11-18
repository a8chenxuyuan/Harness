"""Gateway 包（Phase 12）。

导出：
    * ChannelAdapter / RawMessage / SendResult —— 协议层
    * GatewayRouter —— 路由编排
    * GatewayServer —— 基于 FastAPI 的 HTTP + WebSocket server
    * WebChatAdapter / FeishuAdapter / McpStdioAdapter —— 三个内置 channel
"""

from .channel import ChannelAdapter, RawMessage, SendResult
from .router import GatewayRouter

# Server 和 adapters 依赖 FastAPI / httpx / 三方 SDK，故意延迟 import，
# 保证顶层 ``from harness.gateway import *`` 不会因可选依赖缺失而炸掉。


def __getattr__(name: str):  # noqa: D401 - 动态导出
    """延迟加载重量级成员。"""
    if name == "GatewayServer":
        from .server import GatewayServer
        return GatewayServer
    if name in ("WebChatAdapter", "FeishuAdapter", "McpStdioAdapter"):
        from .adapters import (
            FeishuAdapter,
            McpStdioAdapter,
            WebChatAdapter,
        )
        return {
            "WebChatAdapter": WebChatAdapter,
            "FeishuAdapter": FeishuAdapter,
            "McpStdioAdapter": McpStdioAdapter,
        }[name]
    raise AttributeError(f"module 'harness.gateway' has no attribute {name!r}")


__all__ = [
    # 协议层
    "ChannelAdapter",
    "RawMessage",
    "SendResult",
    # 路由
    "GatewayRouter",
    # 延迟导出（见 __getattr__）
    "GatewayServer",
    "WebChatAdapter",
    "FeishuAdapter",
    "McpStdioAdapter",
]
