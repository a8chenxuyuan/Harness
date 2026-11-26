"""工具市场 / MCP 注册接口出参（VO）。

请求模型在 ``api.dto.tool_dto``。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolMarketItem(BaseModel):
    """工具市场中单个工具的展示项。"""

    name: str = Field(..., description="工具名（注册名）")
    description: str = Field(default="", description="工具说明")
    readonly: bool = Field(default=True, description="是否只读；False=写类工具，调试面板拒绝执行")
    parameters: dict[str, Any] = Field(default_factory=dict, description="入参 JSON Schema")
    source: str = Field(default="builtin", description="来源：builtin（内置）/ mcp（外部 MCP server）")
    server: str | None = Field(default=None, description="来源 MCP server 名；builtin 工具为 null")


class ToolMarketResponse(BaseModel):
    """GET /tools/market 响应体 —— 内置 + MCP 工具聚合列表。"""

    items: list[ToolMarketItem] = Field(default_factory=list, description="全部工具，按名称排序")
    total: int = Field(default=0, description="总数")


class ToolDebugResponse(BaseModel):
    """POST /tools/{name}/debug 响应体 —— 调试执行结果。"""

    ok: bool = Field(..., description="是否执行成功")
    output: str = Field(default="", description="工具输出")
    error: str | None = Field(default=None, description="失败原因；成功时为 null")
    execution_time_ms: float = Field(default=0.0, description="执行耗时（毫秒）")


class McpServerItem(BaseModel):
    """已注册 MCP server 的展示项。"""

    name: str = Field(..., description="server 唯一标识")
    command: str = Field(..., description="stdio 启动命令")
    args: list[str] = Field(default_factory=list, description="命令行参数")
    env_keys: list[str] = Field(default_factory=list, description="环境变量键名列表（值不回传）")
    registered_at: str = Field(..., description="注册时间（UTC ISO）")
    tools: list[str] = Field(default_factory=list, description="接入的工具名列表")
    tool_count: int = Field(default=0, description="接入的工具数")


class McpServerListResponse(BaseModel):
    """GET /mcp/servers 响应体 —— 已注册 server 列表。"""

    items: list[McpServerItem] = Field(default_factory=list, description="按名称排序")
    total: int = Field(default=0, description="总数")


class McpServerRegisterResponse(BaseModel):
    """POST /mcp/servers 响应体 —— 注册成功后的 server 快照。"""

    server: McpServerItem = Field(..., description="新注册的 server 记录")


class McpServerDeleteResponse(BaseModel):
    """DELETE /mcp/servers/{name} 响应体 —— 注销结果。"""

    deleted: bool = Field(default=True, description="true=确实注销；false=名字不存在")


__all__ = [
    "ToolMarketItem",
    "ToolMarketResponse",
    "ToolDebugResponse",
    "McpServerItem",
    "McpServerListResponse",
    "McpServerRegisterResponse",
    "McpServerDeleteResponse",
]
