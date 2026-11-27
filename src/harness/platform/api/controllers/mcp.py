"""MCP server 注册管理接口（W4-EXT-02）。

对外暴露外部 MCP server 的注册、查询与注销。注册时立即对目标
server 做 stdio 握手验证，可用性有问题直接报错，不注册半可用实例。

接口清单：
    POST   /mcp/servers          注册 MCP server（握手 + 接入工具）
    GET    /mcp/servers          列出已注册 server
    DELETE /mcp/servers/{name}   注销 server（同时回收其工具）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from harness.platform.api.deps import require_role
from harness.platform.api.dto.tool_dto import McpServerRegisterRequest
from harness.platform.api.exceptions import BizError
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse
from harness.platform.api.vo.tool_vo import (
    McpServerDeleteResponse,
    McpServerItem,
    McpServerListResponse,
    McpServerRegisterResponse,
)
from harness.platform.service import tool_market_service as market

router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.post("/servers", response_model=ApiResponse[McpServerRegisterResponse])
async def register_server(
    body: McpServerRegisterRequest,
    user: UserInfo = Depends(require_role("owner", "admin", "machine")),
) -> dict:
    """注册一个外部 MCP server（stdio）。

    注册过程：握手 → tools/list → 工具适配进总注册表 → 断开。
    握手失败（进程起不来 / 协议错误 / 超时）返回 502；重名返回 409。
    注册为进程内内存态，重启后需重新注册。
    """
    record = await market.register_mcp_server(
        name=body.name,
        command=body.command,
        args=body.args,
        env=body.env,
    )
    return {
        "code": 0,
        "message": "ok",
        "data": McpServerRegisterResponse(server=McpServerItem(**record)),
    }


@router.get("/servers", response_model=ApiResponse[McpServerListResponse])
async def list_servers(user: UserInfo = Depends(require_role("owner", "admin", "machine"))) -> dict:
    """列出已注册的 MCP server（按名称排序）。"""
    items = await market.list_mcp_servers()
    return {
        "code": 0,
        "message": "ok",
        "data": McpServerListResponse(
            items=[McpServerItem(**i) for i in items],
            total=len(items),
        ),
    }


@router.delete("/servers/{name}", response_model=ApiResponse[McpServerDeleteResponse])
async def delete_server(name: str, user: UserInfo = Depends(require_role("owner", "admin", "machine"))) -> dict:
    """注销一个 MCP server，并从工具市场回收它接入的工具。

    - 找不到 → BizError(404)
    - 注销成功 → deleted=true
    """
    deleted = await market.delete_mcp_server(name)
    if not deleted:
        raise BizError(status.HTTP_404_NOT_FOUND, f"MCP server {name} not found")
    return {
        "code": 0,
        "message": "ok",
        "data": McpServerDeleteResponse(deleted=True),
    }


__all__ = ["router"]
