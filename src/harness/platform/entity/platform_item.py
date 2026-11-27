"""平台数据拉取实体 — platform_items / channel_fetch_state（W4.1-CHAN-06）。

PlatformItem：从外部平台拉取并归户的数据（消息/待办/资料），
    按 (binding_id, external_id) 幂等，external_id 用平台侧稳定标识。
ChannelFetchState：每个绑定 × 数据源的增量拉取游标与最近同步时间。
"""

from __future__ import annotations

from datetime import datetime, timezone

try:
    from sqlmodel import Field, SQLModel, UniqueConstraint  # type: ignore
except Exception:  # noqa: BLE001
    def Field(*a, **kw): ...  # type: ignore[misc]

    class SQLModel:  # type: ignore[no-redef]
        def __init_subclass__(cls, **kw): ...

    def UniqueConstraint(*a, **kw): ...  # type: ignore[misc]


class PlatformItem(SQLModel, table=True):  # noqa: F811
    """一条归户的平台数据。"""

    __tablename__ = "platform_items"
    __table_args__ = (
        UniqueConstraint("binding_id", "external_id", name="ux_platform_item_ext"),
    )

    id: str = Field(primary_key=True, max_length=36)
    tenant_id: str = Field(index=True, max_length=36)
    # 归户：绑定对应的 harness 用户（channel_bindings.harness_user_id）
    user_id: str = Field(index=True, max_length=36)
    binding_id: str = Field(index=True, max_length=36)
    platform: str = Field(max_length=16)  # wecom / feishu / dingtalk
    source: str = Field(max_length=32)  # profile / approval / ...
    item_type: str = Field(max_length=16)  # profile / todo / message
    external_id: str = Field(max_length=128)  # 平台侧稳定标识（msgid/sp_no）
    title: str = Field(default="", max_length=256)
    summary: str = Field(default="", max_length=1024)
    raw: str = Field(default="{}", max_length=8192)  # 原始数据 JSON（截断）
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="平台侧业务发生时间",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChannelFetchState(SQLModel, table=True):  # noqa: F811
    """增量拉取游标（绑定 × 数据源 唯一）。"""

    __tablename__ = "channel_fetch_state"
    __table_args__ = (
        UniqueConstraint("binding_id", "source", name="ux_fetch_state_binding_source"),
    )

    id: str = Field(primary_key=True, max_length=36)
    binding_id: str = Field(index=True, max_length=36)
    source: str = Field(max_length=32)
    cursor: str = Field(default="", max_length=256)  # 平台侧增量游标
    last_synced_at: datetime | None = Field(default=None)
    last_error: str = Field(default="", max_length=512)


__all__ = ["ChannelFetchState", "PlatformItem"]
