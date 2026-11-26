"""流式工具事件载荷 — 把 ToolCall / ToolResult 转成可序列化明细。

单独成文件：避免 ``streaming.py`` 继续膨胀，同时让 SSE 层与前端复用同一结构。
"""

from __future__ import annotations

from typing import Any

from harness.core.model.types import ToolCall
from harness.core.tool.base import ToolResult


def tool_start_payload(calls: list[ToolCall], step: int) -> dict[str, Any]:
    """tool_start 事件载荷：工具数量 + 每次调用的 id / 名称 / 入参。"""
    return {
        "tool_count": len(calls),
        "step": step,
        "calls": [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in calls
        ],
    }


def tool_end_payload(
    results: list[tuple[ToolCall, ToolResult]], step: int
) -> dict[str, Any]:
    """tool_end 事件载荷：每次调用的成功与否 / 输出 / 错误 / 耗时。"""
    return {
        "tool_count": len(results),
        "step": step,
        "results": [
            {
                "id": call.id,
                "name": call.name,
                "arguments": call.arguments,
                "ok": result.ok,
                "output": result.output,
                "error": result.error,
                "execution_time_ms": result.execution_time_ms,
            }
            for call, result in results
        ],
    }


__all__ = ["tool_start_payload", "tool_end_payload"]
