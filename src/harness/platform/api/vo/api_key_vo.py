"""API Key 管理接口出参（VO）。

请求模型在 ``api.dto.api_key_dto``。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ApiKeyItem(BaseModel):
    """单个 API Key 的脱敏展示项（列表/创建响应共用）。"""

    id: str = Field(..., description="API Key ID")
    name: str = Field(..., description="展示名称")
    key_prefix: str = Field(..., description="key 前缀（hk_ + 8 位，供人工辨认）")
    tenant_id: str = Field(..., description="所属租户")
    created_by: str = Field(..., description="创建人用户 ID")
    scopes: str = Field(default="all", description="权限范围（预留，当前统一 all）")
    is_active: bool = Field(default=True, description="是否启用；False=已吊销")
    last_used_at: str | None = Field(default=None, description="最近使用时间（UTC ISO）；从未使用为 null")
    expires_at: str | None = Field(default=None, description="过期时间（UTC ISO）；null=永不过期")
    created_at: str | None = Field(default=None, description="创建时间（UTC ISO）")


class ApiKeyCreateResponse(BaseModel):
    """POST /api-keys 响应体 —— 新签发的 key（明文仅此一次）。"""

    key: ApiKeyItem = Field(..., description="脱敏记录")
    plaintext: str = Field(..., description="明文 key（hk_...）；只在本次响应出现，请立即保存")


class ApiKeyListResponse(BaseModel):
    """GET /api-keys 响应体 —— 租户下全部 key（按创建时间倒序）。"""

    items: list[ApiKeyItem] = Field(default_factory=list, description="脱敏 key 列表")
    total: int = Field(default=0, description="总数")


class ApiKeyRevokeResponse(BaseModel):
    """DELETE /api-keys/{id} 响应体 —— 吊销结果。"""

    revoked: bool = Field(default=True, description="true=确实吊销；false=key 不存在")


__all__ = [
    "ApiKeyItem",
    "ApiKeyCreateResponse",
    "ApiKeyListResponse",
    "ApiKeyRevokeResponse",
]
