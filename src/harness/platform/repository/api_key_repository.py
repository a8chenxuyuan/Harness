"""ApiKeyRepository — API Key 记录读写（W4-API-01）。"""

from __future__ import annotations

from datetime import datetime, timezone


class ApiKeyRepository:
    """签发落库、哈希查询、列表与吊销。"""

    def __init__(self, session) -> None:
        self.session = session

    async def add(self, record):
        self.session.add(record)
        await self.session.commit()
        return record

    async def get_by_hash(self, key_hash: str):
        """按哈希查 key（鉴权入口用）。"""
        from harness.platform.entity.api_key import ApiKey

        from sqlmodel import select

        result = await self.session.exec(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        )
        return result.first()

    async def get(self, key_id: str):
        from harness.platform.entity.api_key import ApiKey

        return await self.session.get(ApiKey, key_id)

    async def list_for_tenant(self, tenant_id: str) -> list:
        """列出租户下全部 key（跨创建人，owner 视角；按创建时间倒序）。"""
        from harness.platform.entity.api_key import ApiKey

        from sqlmodel import select

        result = await self.session.exec(
            select(ApiKey)
            .where(ApiKey.tenant_id == tenant_id)
            .order_by(ApiKey.created_at.desc())
        )
        return list(result.all())

    async def revoke(self, key_id: str) -> bool:
        """吊销一个 key（is_active=False，幂等）。

        Returns:
            True=存在并已置为禁用；False=key 不存在。
        """
        record = await self.get(key_id)
        if record is None:
            return False
        if record.is_active:
            record.is_active = False
            self.session.add(record)
            await self.session.commit()
        return True

    async def touch_last_used(self, record) -> None:
        """刷新最近使用时间（鉴权成功时调用）。"""
        record.last_used_at = datetime.now(timezone.utc)
        self.session.add(record)
        await self.session.commit()
