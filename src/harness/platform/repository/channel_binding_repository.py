"""ChannelBindingRepository — 平台用户绑定读写（W4-CHAN-05）。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import select

from harness.platform.entity.channel import ChannelBinding


class ChannelBindingRepository:
    """绑定查询、创建/更新（upsert 语义）、注销。"""

    def __init__(self, session) -> None:
        self.session = session

    async def get_by_platform_user(
        self, platform: str, platform_user_id: str
    ) -> ChannelBinding | None:
        """按 (platform, platform_user_id) 查绑定（消息路由 / OAuth 登录用）。"""
        result = await self.session.exec(
            select(ChannelBinding)
            .where(ChannelBinding.platform == platform)
            .where(ChannelBinding.platform_user_id == platform_user_id)
        )
        return result.first()

    async def list_for_user(self, harness_user_id: str) -> list[ChannelBinding]:
        """列出一个 harness 用户名下全部绑定（按创建时间倒序）。"""
        result = await self.session.exec(
            select(ChannelBinding)
            .where(ChannelBinding.harness_user_id == harness_user_id)
            .order_by(ChannelBinding.created_at.desc())
        )
        return list(result.all())

    async def save(self, binding: ChannelBinding) -> ChannelBinding:
        """新增或更新绑定（updated_at 自动刷新）。"""
        binding.updated_at = datetime.now(timezone.utc)
        self.session.add(binding)
        await self.session.commit()
        return binding

    async def get(self, binding_id: str) -> ChannelBinding | None:
        return await self.session.get(ChannelBinding, binding_id)

    async def revoke(self, binding_id: str) -> bool:
        """注销绑定（status=revoked，幂等）。仅调用方负责校验归属。"""
        binding = await self.get(binding_id)
        if binding is None:
            return False
        if binding.status != "revoked":
            binding.status = "revoked"
            self.session.add(binding)
            await self.session.commit()
        return True
