"""AuditRepository — 审计日志表的数据访问。⚠️ SQLModel 延迟加载。

审计日志特点：只写不删（append-only），高频写入。
"""

from __future__ import annotations

from datetime import datetime


class AuditRepository:
    """审计日志表。"""

    def __init__(self, session) -> None:
        self.session = session

    async def log(
        self,
        *,
        tenant_id: str,
        user_id: str,
        action: str,
        target: str = "",
        result: str = "success",
        session_id: str | None = None,
        detail_json: str = "{}",
    ):
        """写一条审计日志。"""
        from harness.platform.entity.audit_log import AuditLog

        entry = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            action=action,
            target=target,
            result=result,
            detail_json=detail_json,
        )
        self.session.add(entry)
        await self.session.commit()
        return entry

    async def list_by_tenant(
        self,
        tenant_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
        action: str | None = None,
        since: datetime | None = None,
    ):
        """按租户查日志，支持 action + 时间范围过滤。"""
        from sqlmodel import select
        from harness.platform.entity.audit_log import AuditLog

        stmt = select(AuditLog).where(AuditLog.tenant_id == tenant_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if since:
            stmt = stmt.where(AuditLog.created_at >= since)
        stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.exec(stmt)
        return list(result.all())
