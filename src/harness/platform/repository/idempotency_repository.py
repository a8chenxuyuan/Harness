"""IdempotencyRepository — 幂等键表的数据访问（W3-KERN-02）。"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class IdempotencyRepository:
    """按 (tenant, scope, key) 查询、占位、完成与释放。"""

    def __init__(self, session) -> None:
        self.session = session

    async def lookup(self, tenant_id: str, scope: str, key: str):
        """按三元组查询幂等记录（无则 None）。"""
        from sqlmodel import select

        from harness.platform.entity.idempotency_key import IdempotencyRecord

        result = await self.session.exec(
            select(IdempotencyRecord).where(
                IdempotencyRecord.tenant_id == tenant_id,
                IdempotencyRecord.scope == scope,
                IdempotencyRecord.key == key,
            )
        )
        return result.first()

    async def add(self, record):
        """插入占位记录；唯一键冲突时回滚并返回 False。"""
        from sqlalchemy.exc import IntegrityError

        try:
            self.session.add(record)
            await self.session.commit()
            return True
        except IntegrityError:
            # 并发下另一个请求已占位，交回调用方重新读取
            await self.session.rollback()
            return False

    async def complete(self, record, response_json: str) -> None:
        """置为 succeeded 并写入响应缓存。"""
        from datetime import datetime, timezone

        record.status = "succeeded"
        record.response_json = response_json
        record.updated_at = datetime.now(timezone.utc)
        self.session.add(record)
        await self.session.commit()

    async def delete(self, record) -> None:
        """删除记录（失败释放，允许同 key 重试）。"""
        await self.session.delete(record)
        await self.session.commit()

    async def delete_in_progress(self) -> int:
        """清空所有 in_progress 记录（服务重启恢复用），返回行数。"""
        from sqlalchemy import delete

        from harness.platform.entity.idempotency_key import IdempotencyRecord

        result = await self.session.exec(
            delete(IdempotencyRecord).where(
                IdempotencyRecord.status == "in_progress"
            )
        )
        await self.session.commit()
        return int(result.rowcount or 0)
