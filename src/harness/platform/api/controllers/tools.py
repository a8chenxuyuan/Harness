"""工具目录 / 市场接口（W4-EXT-02）。

接口清单：
    GET  /tools              内置工具目录（顺序稳定，供快照测试）
    GET  /tools/market       全量工具市场（内置 + MCP，标注来源）
    POST /tools/{name}/debug 只读工具调试执行（写类拒绝、超时保护）
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status

from harness.platform.api.deps import require_role
from harness.platform.api.dto.tool_dto import ToolDebugRequest
from harness.platform.api.exceptions import BizError
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse
from harness.platform.api.vo.tool_vo import ToolDebugResponse, ToolMarketItem, ToolMarketResponse
from harness.platform.service import tool_market_service as market

router = APIRouter(prefix="/tools", tags=["tools"])


def tool_catalog() -> list[dict[str, Any]]:
    """构造内置工具目录（顺序稳定，便于快照测试）。

    Returns:
        每个工具一个 dict：name / description / readonly / parameters。
    """
    from harness.core.tool.builtin import (
        BashTool,
        HttpGetTool,
        ReadFileTool,
        WriteFileTool,
    )

    catalog: list[dict[str, Any]] = []
    for tool in (ReadFileTool(), WriteFileTool(), BashTool(), HttpGetTool()):
        catalog.append(
            {
                "name": tool.name,
                "description": tool.description,
                "readonly": tool.readonly,
                "parameters": tool.parameters,
            }
        )
    return catalog


@router.get("", response_model=ApiResponse[dict[str, Any]])
async def list_tools(user: UserInfo = Depends(require_role("owner", "admin", "machine"))) -> dict[str, Any]:
    """列出当前 runtime 注册的内置工具。"""
    items = tool_catalog()
    return {
        "code": 0,
        "message": "ok",
        "data": {"items": items, "total": len(items)},
    }


# ---------------------------------------------------------------------------
# GET /tools/market —— 全量工具市场
# ---------------------------------------------------------------------------

@router.get("/market", response_model=ApiResponse[ToolMarketResponse])
async def tool_market(user: UserInfo = Depends(require_role("owner", "admin", "machine"))) -> dict:
    """聚合全部工具（内置 + 已注册 MCP server 的工具）。

    每项标注来源 source（builtin / mcp）与来源 server 名，
    按工具名排序。前端工具市场页与调试面板都以这个接口为准。
    """
    items = await market.list_market()
    return {
        "code": 0,
        "message": "ok",
        "data": ToolMarketResponse(
            items=[ToolMarketItem(**i) for i in items],
            total=len(items),
        ),
    }


# ---------------------------------------------------------------------------
# POST /tools/{name}/debug —— 只读工具调试执行
# ---------------------------------------------------------------------------

@router.post("/{name}/debug", response_model=ApiResponse[ToolDebugResponse])
async def debug_tool(
    name: str,
    body: ToolDebugRequest,
    user: UserInfo = Depends(require_role("owner", "admin", "machine")),
) -> dict:
    """调试执行一个工具（安全护栏见 service 层）。

    - 写类工具（readonly=False）→ 403
    - 缺少必填参数 → 422
    - 执行超时（>30s）→ 504
    - 执行结果无论成败都以 200 返回（ok=False 表示工具自身报错）
    """
    result = await market.debug_tool(name, body.arguments)
    return {
        "code": 0,
        "message": "ok",
        "data": ToolDebugResponse(**result),
    }


__all__ = ["router", "tool_catalog"]
