"""认证域入参（DTO）。

只放请求模型；响应模型在 ``api.vo.auth``。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """POST /api/v1/auth/login 请求体。"""

    username: str = Field(..., min_length=1, max_length=128, description="用户名或邮箱")
    password: str = Field(..., min_length=1, max_length=256, description="明文密码（HTTPS 传输）")


class RefreshRequest(BaseModel):
    """POST /api/v1/auth/refresh 请求体。

    refresh token 走 JSON body 而非 query 参数，避免 token 被访问日志记录。
    """

    refresh_token: str = Field(..., min_length=1, description="refresh token")


class RegisterRequest(BaseModel):
    """POST /api/v1/auth/register 请求体。"""

    username: str = Field(..., min_length=3, max_length=64)
    email: str = Field(..., max_length=256)
    password: str = Field(..., min_length=8, max_length=256)
    tenant_name: str | None = Field(default=None, description="新建租户名（不传则加入默认租户）")


__all__ = ["LoginRequest", "RefreshRequest", "RegisterRequest"]
