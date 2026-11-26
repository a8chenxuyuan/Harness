"""流式领域事件与消息内容块构造。

与传输格式解耦：控制器（SSE）只负责序列化，不关心内容块如何拼接。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StreamEvent:
    """流式领域事件（data 为可 JSON 序列化的字典）。"""

    event: str
    data: dict[str, Any] = field(default_factory=dict)


def append_text_part(parts: list[dict], delta: str) -> None:
    """把增量文本并入最后一个 text 块；上一块是工具块时新开一块。"""
    last = parts[-1] if parts else None
    if isinstance(last, dict) and last.get("type") == "text":
        last["text"] = f"{last.get('text') or ''}{delta}"
    else:
        parts.append({"type": "text", "text": delta})


def tool_part(item: dict) -> dict:
    """把工具执行结果转成消息内容块（前端按 tool_call 渲染）。"""
    ok = bool(item.get("ok"))
    content = (
        item.get("output") if ok else (item.get("error") or item.get("output") or "")
    )
    return {
        "type": "tool_call",
        "name": item.get("name") or "",
        "arguments": item.get("arguments") or {},
        "content": content or "",
        "ok": ok,
        "execution_time_ms": item.get("execution_time_ms") or 0,
    }


__all__ = ["StreamEvent", "append_text_part", "tool_part"]
