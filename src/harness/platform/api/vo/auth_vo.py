"""认证域出参（VO）。

只放响应模型；请求模型在 ``api.dto.auth``。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginResponse(BaseModel):
    """POST /api/v1/auth/login 成功响应。"""

    access_token: str = Field(..., description="JWT access token，15min")
    refresh_token: str = Field(..., description="JWT refresh token，7d")
    token_type: str = Field("bearer")
    expires_in: int = Field(900, description="access_token 有效期秒数")


class UserInfo(BaseModel):
    """当前登录用户上下文（JWT 解析结果 + /auth/me 出参）。"""

    user_id: str
    tenant_id: str
    role: str = Field(..., description="owner | admin | member")


class MeInfo(UserInfo):
    """/auth/me 出参：用户信息 + 可见页面清单（多角色并集）。"""

    allowed_pages: list[str] = Field(default_factory=list, description="可见页面 key 列表")


__all__ = ["LoginResponse", "MeInfo", "UserInfo"]
