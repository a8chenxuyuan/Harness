"""工具市场 / MCP 注册接口入参（DTO）。

响应模型在 ``api.vo.tool_vo``。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class McpServerRegisterRequest(BaseModel):
    """POST /mcp/servers 请求体 —— 注册一个外部 MCP server（stdio）。

    注册时会立即握手验证可用性，握手失败返回 502，不会注册半可用的 server。
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="server 唯一标识，重复注册返回 409",
    )
    command: str = Field(..., min_length=1, description="要启动的可执行程序，如 npx / uvx / python")
    args: list[str] = Field(
        default_factory=list,
        max_length=64,
        description="命令行参数列表，如 ['-y', '@modelcontextprotocol/server-filesystem', '/tmp']",
    )
    env: dict[str, str] = Field(
        default_factory=dict,
        description="额外环境变量（与当前进程环境合并传给子进程）",
    )


class ToolDebugRequest(BaseModel):
    """POST /tools/{name}/debug 请求体 —— 调试执行一个只读工具。"""

    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="工具入参（JSON），按工具 schema 传；缺失必填参数返回 422",
    )


__all__ = ["McpServerRegisterRequest", "ToolDebugRequest"]
