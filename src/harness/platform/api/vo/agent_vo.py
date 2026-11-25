"""Agent 域出参（VO）。

请求模型在 ``api.dto.agent``。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentRunResponse(BaseModel):
    """POST /api/v1/agents/run 响应体。"""

    run_id: str = Field(..., description="运行唯一 id（也是 session_id）")
    status: str = Field(..., description="success | failed | running")
    output: str | None = Field(default=None, description="Agent 最终回答")
    metrics: dict[str, Any] | None = Field(default=None, description="耗时、token 数等指标")


__all__ = ["AgentRunResponse"]
