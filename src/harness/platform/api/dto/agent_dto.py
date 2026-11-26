"""Agent 域入参（DTO）。

只放请求模型；响应模型在 ``api.vo.agent``。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentRunRequest(BaseModel):
    """POST /api/v1/agents/run 请求体。"""

    goal: str = Field(..., min_length=1, max_length=4000, description="人类可读的目标描述")
    mode: str = Field(
        default="single",
        pattern="^(single|coordinator)$",
        description="single=直接跑单 Agent, coordinator=走 Plan→Review→Executor",
    )
    conversation_id: str | None = Field(default=None, description="续跑时传已有会话 id")


__all__ = ["AgentRunRequest"]
