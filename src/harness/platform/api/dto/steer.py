"""Steering 相关 DTO。

从 gateway/steering_api.py 迁过来，保持 pydantic v2 风格，同时
在 gateway 层做 re-export 保持向后兼容。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SteerRequest(BaseModel):
    """POST /api/v1/steer 请求体。"""

    session_id: str = Field(..., description="目标会话 id")
    message: str = Field(default="", description="inject 时要追加的新消息")
    kind: Literal["interrupt", "continue", "inject"] = Field(..., description="操作类型")

    model_config = {"extra": "forbid"}


class SteerResponse(BaseModel):
    """steer 成功响应。"""

    ok: bool = True
    session_id: str
    action: Literal["interrupt", "continue", "inject"]


__all__ = ["SteerRequest", "SteerResponse"]
