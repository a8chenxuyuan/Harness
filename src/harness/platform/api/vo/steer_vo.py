"""Steering 域出参（VO）。

请求模型在 ``api.dto.steer``。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SteerResponse(BaseModel):
    """POST /api/v1/steer 成功响应。"""

    ok: bool = True
    session_id: str
    action: Literal["interrupt", "continue", "inject"]


__all__ = ["SteerResponse"]
