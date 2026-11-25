"""MCP (Model Context Protocol) 接入层（Phase 15）。

对外导出：
    * McpClient — JSON-RPC 2.0 over stdio 的客户端
    * McpError — MCP 协议错误
"""

from .client import McpClient, McpError

__all__ = ["McpClient", "McpError"]
