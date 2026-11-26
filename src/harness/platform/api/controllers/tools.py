"""工具目录接口（GET /tools）。

对外暴露内置工具的名称、描述、只读标记与 JSON Schema，供前端 / 外部
Agent 展示「当前 runtime 能做什么」。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from harness.platform.api.deps import get_current_user
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse

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
async def list_tools(user: UserInfo = Depends(get_current_user)) -> dict[str, Any]:
    """列出当前 runtime 注册的内置工具。"""
    items = tool_catalog()
    return {
        "code": 0,
        "message": "ok",
        "data": {"items": items, "total": len(items)},
    }


__all__ = ["router", "tool_catalog"]
