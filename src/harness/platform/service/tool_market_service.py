"""Tool 市场与 MCP server 注册服务（W4-EXT-02）。

职责：
    1. 维护进程内唯一的工具总注册表：内置 4 工具 + 已注册 MCP server 的工具
    2. MCP server 注册：握手 → 拉工具清单 → 适配成 McpTool 注册进总注册表
    3. 工具市场：聚合内置 + MCP 工具，标注来源（builtin / mcp）
    4. 工具调试：只读工具安全执行（写类拒绝、参数必填校验、超时保护）

不做：
    - 不做 MCP server 配置持久化（内存态，进程重启后需重新注册）
    - 不做长连接管理（McpTool 每次调用新建连接，见 tool_adapter.py）
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import status as http_status

from harness.core.tool.base import BaseTool
from harness.core.tool.registry import ToolRegistry
from harness.integrations.mcp.client import McpClient, McpError
from harness.integrations.mcp.tool_adapter import McpTool
from harness.platform.api.exceptions import BizError

log = logging.getLogger(__name__)

# 握手超时（秒）：注册时给 MCP server 的启动 + initialize 预算
_HANDSHAKE_TIMEOUT = 15.0
# 调试执行超时（秒）
_DEBUG_TIMEOUT = 30.0


@dataclass
class McpServerRecord:
    """一个已注册 MCP server 的元数据与状态。

    Attributes:
        name: 唯一标识（用户指定）。
        command/args/env: stdio 启动配置。
        registered_at: 注册时间（UTC ISO）。
        tools: 该 server 注册进总注册表的工具名列表（注销时按此回收）。
        tool_defs: tools/list 的原始返回（给市场展示与调试面板校验）。
    """

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    registered_at: str = ""
    tools: list[str] = field(default_factory=list)
    tool_defs: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 单例状态
# ---------------------------------------------------------------------------

_state_registry: ToolRegistry | None = None
_state_servers: dict[str, McpServerRecord] = {}


def get_tool_registry() -> ToolRegistry:
    """返回进程内唯一的工具总注册表（内置工具懒加载）。"""
    global _state_registry
    if _state_registry is None:
        _state_registry = ToolRegistry()
        from harness.core.tool.builtin import BashTool, HttpGetTool, ReadFileTool, WriteFileTool

        for tool in (ReadFileTool(), WriteFileTool(), BashTool(), HttpGetTool()):
            _state_registry.register(tool)
    return _state_registry


def reset_tool_market_service() -> None:
    """清空单例状态，仅供测试使用。"""
    global _state_registry
    _state_registry = None
    _state_servers.clear()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# MCP server 注册 / 注销
# ---------------------------------------------------------------------------

async def register_mcp_server(
    *,
    name: str,
    command: str,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """注册一个外部 MCP server（stdio）并把它暴露的工具接入总注册表。

    流程：connect 握手 → tools/list 拉清单 → 逐个适配成 McpTool 注册 →
    断开连接。握手或拉清单失败抛 BizError(502)，不注册任何工具。

    Returns:
        server 记录 dict（含接入的工具清单摘要）。
    """
    registry = get_tool_registry()
    if name in _state_servers:
        raise BizError(http_status.HTTP_409_CONFLICT, f"MCP server {name} 已注册")

    client = McpClient(command, args, env)
    try:
        try:
            await asyncio.wait_for(client.connect(), timeout=_HANDSHAKE_TIMEOUT)
            tool_defs = await asyncio.wait_for(client.tools_list(), timeout=_HANDSHAKE_TIMEOUT)
        except (asyncio.TimeoutError, RuntimeError, McpError, OSError) as exc:
            raise BizError(
                http_status.HTTP_502_BAD_GATEWAY,
                f"MCP server {name} 握手失败：{exc}",
            ) from exc
    finally:
        await client.close()

    record = McpServerRecord(
        name=name,
        command=command,
        args=list(args or []),
        env=dict(env or {}),
        registered_at=_utc_now_iso(),
        tool_defs=tool_defs,
    )

    # 逐个适配注册；同名工具后注册覆盖前注册（ToolRegistry 会打 warning）
    for td in tool_defs:
        tool = McpTool(
            server_name=name,
            name=str(td.get("name", "")),
            description=str(td.get("description", "")),
            input_schema=td.get("inputSchema") or {},
            command=command,
            args=record.args,
            env=record.env,
        )
        if not tool.name:
            continue
        registry.register(tool)
        record.tools.append(tool.name)

    _state_servers[name] = record
    log.info("ToolMarketService: 注册 MCP server %s，接入 %d 个工具", name, len(record.tools))
    return _server_to_dict(record)


async def list_mcp_servers() -> list[dict[str, Any]]:
    """列出已注册的 MCP server（按注册名排序）。"""
    return [_server_to_dict(_state_servers[k]) for k in sorted(_state_servers)]


async def delete_mcp_server(name: str) -> bool:
    """注销一个 MCP server，并从总注册表移除它接入的工具。

    Returns:
        True=确实注销；False=名字不存在。
    """
    record = _state_servers.pop(name, None)
    if record is None:
        return False
    registry = get_tool_registry()
    removed: list[str] = []
    for tool_name in record.tools:
        if _pop_tool(registry, tool_name):
            removed.append(tool_name)
    log.info("ToolMarketService: 注销 MCP server %s，移除工具 %s", name, removed)
    return True


def _pop_tool(registry: ToolRegistry, tool_name: str) -> bool:
    """从 ToolRegistry 移除一个工具；不存在返回 False。"""
    if tool_name not in registry:
        return False
    registry._tools.pop(tool_name, None)  # noqa: SLF001 - 注册表未提供删除接口，内存态可控
    return True


def _server_to_dict(record: McpServerRecord) -> dict[str, Any]:
    """server 记录 → API dict（env 不外泄，只回键名）。"""
    return {
        "name": record.name,
        "command": record.command,
        "args": list(record.args),
        "env_keys": sorted(record.env.keys()),
        "registered_at": record.registered_at,
        "tools": list(record.tools),
        "tool_count": len(record.tools),
    }


# ---------------------------------------------------------------------------
# 工具市场
# ---------------------------------------------------------------------------

async def list_market() -> list[dict[str, Any]]:
    """聚合全部工具（内置 + MCP），标注来源，按名称排序。"""
    registry = get_tool_registry()
    items: list[dict[str, Any]] = []
    for tool in registry:
        source = "mcp" if isinstance(tool, McpTool) else "builtin"
        item: dict[str, Any] = {
            "name": tool.name,
            "description": tool.description,
            "readonly": tool.readonly,
            "parameters": tool.parameters,
            "source": source,
            "server": tool.server_name if isinstance(tool, McpTool) else None,
        }
        items.append(item)
    return sorted(items, key=lambda i: i["name"])


# ---------------------------------------------------------------------------
# 工具调试
# ---------------------------------------------------------------------------

async def debug_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """调试执行一个工具（只允许只读工具）。

    安全护栏：
        - 写类工具（readonly=False）一律拒绝（403）
        - 必填参数缺失拒绝（422）
        - 整体 30s 超时保护（504）

    Returns:
        ToolResult 风格 dict：ok / output / error / execution_time_ms。
    """
    registry = get_tool_registry()
    try:
        tool = registry.get(name)
    except KeyError as exc:
        raise BizError(http_status.HTTP_404_NOT_FOUND, f"tool {name} not found") from exc

    if not tool.readonly:
        raise BizError(
            http_status.HTTP_403_FORBIDDEN,
            f"tool {name} 是写类工具，调试面板只允许执行只读工具",
        )

    args = dict(arguments or {})
    _check_required_args(tool, args)

    started = time.monotonic()
    try:
        result = await asyncio.wait_for(tool.execute(**args), timeout=_DEBUG_TIMEOUT)
    except asyncio.TimeoutError as exc:
        raise BizError(http_status.HTTP_504_GATEWAY_TIMEOUT, f"调试执行超时（>{_DEBUG_TIMEOUT}s）") from exc

    elapsed_ms = round((time.monotonic() - started) * 1000, 2)
    return {
        "ok": result.ok,
        "output": result.output,
        "error": result.error,
        "execution_time_ms": result.execution_time_ms or elapsed_ms,
    }


def _check_required_args(tool: BaseTool, args: dict[str, Any]) -> None:
    """按工具 JSON Schema 的 required 字段做最小校验（不引第三方 jsonschema）。"""
    required = tool.parameters.get("required", []) if isinstance(tool.parameters, dict) else []
    missing = [key for key in required if key not in args]
    if missing:
        raise BizError(
            422,
            f"缺少必填参数：{', '.join(missing)}",
        )


__all__ = [
    "get_tool_registry",
    "reset_tool_market_service",
    "register_mcp_server",
    "list_mcp_servers",
    "delete_mcp_server",
    "list_market",
    "debug_tool",
]
