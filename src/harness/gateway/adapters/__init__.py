"""Gateway 内置 channel adapters（Phase 12）。

按 "壳优先" 原则实现：FeishuAdapter / McpStdioAdapter 在配置缺失时不
抛模块级 ImportError，而是在实例方法里抛 ``ConfigurationError``——
server 启动时只注册 config 存在的 adapter，其他 adapter 壳对象会被跳过。
"""

from .feishu import FeishuAdapter
from .mcp_stdio import McpStdioAdapter
from .webchat import WebChatAdapter

__all__ = [
    "WebChatAdapter",
    "FeishuAdapter",
    "McpStdioAdapter",
]
