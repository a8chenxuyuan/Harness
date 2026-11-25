"""Agent 运行相关 DTO（对应 AgentController 的入参/出参）。"""

from __future__ import annotations

from typing import Any

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


class AgentRunResponse(BaseModel):
    """POST /api/v1/agents/run 响应体。"""

    run_id: str = Field(..., description="运行唯一 id（也是 session_id）")
    status: str = Field(..., description="success | failed | running")
    output: str | None = Field(default=None, description="Agent 最终回答")
    metrics: dict[str, Any] | None = Field(default=None, description="耗时、token 数等指标")


__all__ = ["AgentRunRequest", "AgentRunResponse"]
