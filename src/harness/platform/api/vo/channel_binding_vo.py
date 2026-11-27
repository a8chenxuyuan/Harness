"""渠道绑定 VO（W4-CHAN-05）。"""

from __future__ import annotations

from pydantic import BaseModel


class BindingItem(BaseModel):
    """一条绑定（脱敏：不含凭证密文）。"""

    id: str
    platform: str
    platform_user_id: str
    display_name: str = ""
    status: str = "active"
    last_login_at: str | None = None
    created_at: str


class BindingListResponse(BaseModel):
    items: list[BindingItem]
    total: int


class BindingRevokeResponse(BaseModel):
    revoked: bool


__all__ = ["BindingItem", "BindingListResponse", "BindingRevokeResponse"]
