"""Session 域入参（DTO）。

只放请求模型；响应模型在 ``api.vo.session``。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    """POST /api/v1/sessions 请求体。"""

    title: str = Field(default="", max_length=256)
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = ["SessionCreateRequest"]
