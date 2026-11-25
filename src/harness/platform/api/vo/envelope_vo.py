"""统一响应封装（对应 Java 的 Result<T> / AjaxResult）。

所有 Controller 出参都用 :class:`ApiResponse` 包裹，错误统一由
``api.exceptions.register_exception_handlers`` 产出 :class:`ApiErrorResponse`。
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """成功响应。

    Attributes:
        code: 业务码，0 表示成功。
        message: 人类可读的状态描述。
        data: 业务数据，类型由泛型 T 决定。
    """

    model_config = {"arbitrary_types_allowed": True}

    code: int = Field(default=0, description="业务码，0=成功")
    message: str = Field(default="ok", description="状态描述")
    data: T | None = Field(default=None, description="业务数据")


class ApiErrorResponse(BaseModel):
    """失败响应，由异常处理器统一生成。

    Attributes:
        code: 业务错误码。
        message: 简短错误描述。
        detail: 可选详细信息。
    """

    code: int = Field(..., description="业务错误码")
    message: str = Field(..., description="错误描述")
    detail: str | None = Field(default=None, description="详细信息")


__all__ = ["ApiResponse", "ApiErrorResponse"]
