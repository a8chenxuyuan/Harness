"""Gateway 包 —— 渠道接入抽象层。

本包只做**协议层 + 路由编排**，不包含 HTTP 服务端实现。
HTTP/REST/WebSocket 接口层现在归 :mod:`harness.platform.api` 管。

导出：
    * ChannelAdapter / RawMessage / SendResult —— 渠道协议抽象
    * GatewayRouter —— 消息路由编排（dispatch / run_all）

延迟导出（避免可选依赖缺失）：
    * WebChatAdapter / FeishuAdapter / McpStdioAdapter —— 三个内置渠道
    * GatewayServer —— 便捷启动 facade（内部调 harness.app.create_app）
"""

from .channel import ChannelAdapter, RawMessage, SendResult
from .router import GatewayRouter


def __getattr__(name: str):  # noqa: D401 - 动态导出
    """延迟加载可选成员（依赖 FastAPI / 三方 SDK）。"""
    if name == "GatewayServer":
        from .server import GatewayServer
        return GatewayServer
    if name in ("WebChatAdapter", "FeishuAdapter", "McpStdioAdapter"):
        from .adapters import FeishuAdapter, McpStdioAdapter, WebChatAdapter
        return {
            "WebChatAdapter": WebChatAdapter,
            "FeishuAdapter": FeishuAdapter,
            "McpStdioAdapter": McpStdioAdapter,
        }[name]
    raise AttributeError(f"module 'harness.integrations.gateway' has no attribute {name!r}")


__all__ = [
    # 协议层
    "ChannelAdapter",
    "RawMessage",
    "SendResult",
    # 路由编排
    "GatewayRouter",
    # 延迟导出
    "GatewayServer",
    "WebChatAdapter",
    "FeishuAdapter",
    "McpStdioAdapter",
]
