"""消息域入参（DTO）。

只放请求模型；响应模型在 ``api.vo.message``。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MessageCreateRequest(BaseModel):
    """POST /api/v1/sessions/{session_id}/messages 请求体。"""

    role: str = Field(
        default="user",
        pattern="^(user|assistant|system|tool)$",
        description="消息角色",
    )
    text: str = Field(default="", max_length=100_000, description="纯文本内容")
    parts: list[dict[str, Any]] = Field(
        default_factory=list, description="内容块数组，为空时按 text 生成一个 text 块"
    )
    parent_id: str | None = Field(default=None, description="分支来源消息 id")
    status: str = Field(
        default="completed", pattern="^(streaming|completed|failed|cancelled)$"
    )


__all__ = ["MessageCreateRequest"]
