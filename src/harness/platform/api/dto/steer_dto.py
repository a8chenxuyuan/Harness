"""Steering 域入参（DTO）。

只放请求模型；响应模型在 ``api.vo.steer``。
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


__all__ = ["SteerRequest"]
