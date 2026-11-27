"""WebhookRepository — 订阅与投递记录读写（W4-CHAN-03）。"""

from __future__ import annotations


class WebhookRepository:
    """订阅 CRUD、启用订阅查询、投递记录写入与查询。"""

    def __init__(self, session) -> None:
        self.session = session

    # --- 订阅 ---------------------------------------------------------------

    async def add_subscription(self, record):
        self.session.add(record)
        await self.session.commit()
        return record

    async def get_subscription(self, webhook_id: str):
        from harness.platform.entity.webhook import WebhookSubscription

        return await self.session.get(WebhookSubscription, webhook_id)

    async def list_subscriptions(self, tenant_id: str) -> list:
        """列出租户下全部订阅（按创建时间倒序）。"""
        from harness.platform.entity.webhook import WebhookSubscription

        from sqlmodel import select

        result = await self.session.exec(
            select(WebhookSubscription)
            .where(WebhookSubscription.tenant_id == tenant_id)
            .order_by(WebhookSubscription.created_at.desc())
        )
        return list(result.all())

    async def list_active_subscriptions(self) -> list:
        """列出全库启用的订阅（调度器用，事件侧再做租户过滤）。"""
        from harness.platform.entity.webhook import WebhookSubscription

        from sqlmodel import select

        result = await self.session.exec(
            select(WebhookSubscription).where(WebhookSubscription.is_active)
        )
        return list(result.all())

    async def delete_subscription(self, webhook_id: str) -> bool:
        """删除订阅及其全部投递记录。

        Returns:
            True=已删除；False=订阅不存在。
        """
        record = await self.get_subscription(webhook_id)
        if record is None:
            return False
        for delivery in await self.list_deliveries(webhook_id, limit=0):
            await self.session.delete(delivery)
        await self.session.delete(record)
        await self.session.commit()
        return True

    # --- 投递记录 ------------------------------------------------------------

    async def add_delivery(self, record):
        self.session.add(record)
        await self.session.commit()
        return record

    async def list_deliveries(self, subscription_id: str, limit: int = 50) -> list:
        """按订阅查投递记录（最新在前；limit<=0 表示不分页，删订阅时用）。"""
        from harness.platform.entity.webhook import WebhookDelivery

        from sqlmodel import select

        stmt = (
            select(WebhookDelivery)
            .where(WebhookDelivery.subscription_id == subscription_id)
            .order_by(WebhookDelivery.created_at.desc())
        )
        if limit > 0:
            stmt = stmt.limit(limit)
        result = await self.session.exec(stmt)
        return list(result.all())
