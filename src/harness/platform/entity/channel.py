"""渠道接入实体 — channel_apps / channel_bindings（W4-CHAN-05）。

ChannelApp：各平台应用凭据登记（企微 corp_id/secret 等），
    平台密钥一律加密落库，不存明文。
ChannelBinding：平台用户 ↔ harness 用户 的绑定关系，
    消息链路按 platform_user_id 查绑定路由到正确租户/用户。
"""

from __future__ import annotations

from datetime import datetime, timezone

try:
    from sqlmodel import Field, SQLModel  # type: ignore
except Exception:  # noqa: BLE001
    class Field:  # type: ignore[no-redef]
        def __init__(self, *a, **kw): ...

    class SQLModel:  # type: ignore[no-redef]
        def __init_subclass__(cls, **kw): ...


class ChannelApp(SQLModel, table=True):  # noqa: F811
    """平台应用凭据登记（W4-CHAN-05，多应用/多租户的基础表）。

    密钥字段（secret / aes_key）存密文；token（回调验签用）为低敏
    自定义字符串，明文存储。env 配置仍作兜底来源。
    """

    __tablename__ = "channel_apps"

    id: str = Field(primary_key=True, max_length=36)
    platform: str = Field(index=True, max_length=32)  # wecom / feishu / dingtalk
    corp_id: str = Field(default="", max_length=64)  # 企微企业ID / 平台应用ID
    agent_id: str = Field(default="", max_length=64)  # 企微应用 agentid
    secret_enc: str = Field(default="", max_length=1024)  # 平台密钥（密文）
    token: str = Field(default="", max_length=128)  # 回调验签 token
    encoding_aes_key_enc: str = Field(default="", max_length=256)  # 回调 AESKey（密文）
    mode: str = Field(default="http_callback", max_length=32)  # http_callback / long_conn
    owner_scope: str = Field(default="shared-byo", max_length=32)  # 应用归属
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChannelBinding(SQLModel, table=True):  # noqa: F811
    """平台用户 ↔ harness 用户绑定（W4-CHAN-05）。

    (platform, platform_user_id) 唯一；消息链路先按它查绑定，
    命中则用绑定里的 harness_user_id + tenant_id 跑 Agent。
    """

    __tablename__ = "channel_bindings"

    id: str = Field(primary_key=True, max_length=36)
    platform: str = Field(index=True, max_length=32)
    platform_user_id: str = Field(max_length=128)  # 企微 UserID / 平台 open_id
    harness_user_id: str = Field(index=True, max_length=36)
    tenant_id: str = Field(index=True, max_length=36)
    display_name: str = Field(default="", max_length=128)  # 平台昵称/备注
    # 平台凭证密文（OAuth user_access_token 等，JSON 加密；当前企微
    # 网页授权仅返回 userid，字段为扩展预留）
    credential_enc: str = Field(default="", max_length=4096)
    status: str = Field(default="active", max_length=16)  # active / revoked
    last_login_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
