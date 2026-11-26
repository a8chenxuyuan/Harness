"""AuditRepository — 审计日志表的数据访问。⚠️ SQLModel 延迟加载。

审计日志特点：只写不删（append-only），高频写入、低频查询。
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
        user_id: str | None = None,
        session_id: str | None = None,
        result: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ):
        """按租户查日志，支持动作 / 用户 / 会话 / 结果 / 时间范围过滤。"""
        from sqlmodel import select

        from harness.platform.entity.audit_log import AuditLog

        stmt = self._filtered(select(AuditLog), tenant_id, action, user_id, session_id, result, since, until)
        stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
        result_rows = await self.session.exec(stmt)
        return list(result_rows.all())

    async def count_by_tenant(
        self,
        tenant_id: str,
        *,
        action: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        result: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> int:
        """与 ``list_by_tenant`` 相同过滤条件下的总条数。"""
        from sqlalchemy import func, select

        from harness.platform.entity.audit_log import AuditLog

        stmt = self._filtered(
            select(func.count()).select_from(AuditLog),
            tenant_id,
            action,
            user_id,
            session_id,
            result,
            since,
            until,
        )
        rows = (await self.session.exec(stmt)).all()
        if not rows:
            return 0
        value = rows[0]
        return int(value) if isinstance(value, (int, float)) else int(value[0])

    async def list_actions(self, tenant_id: str) -> list[str]:
        """本租户出现过的动作标识（去重升序）。"""
        from sqlmodel import select

        from harness.platform.entity.audit_log import AuditLog

        stmt = (
            select(AuditLog.action)
            .where(AuditLog.tenant_id == tenant_id)
            .distinct()
            .order_by(AuditLog.action)
        )
        rows = (await self.session.exec(stmt)).all()
        return [str(item) for item in rows]

    @staticmethod
    def _filtered(
        stmt,
        tenant_id: str,
        action: str | None,
        user_id: str | None,
        session_id: str | None,
        result: str | None,
        since: datetime | None,
        until: datetime | None,
    ):
        """给 select 追加租户与可选过滤条件。"""
        from harness.platform.entity.audit_log import AuditLog

        stmt = stmt.where(AuditLog.tenant_id == tenant_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if session_id:
            stmt = stmt.where(AuditLog.session_id == session_id)
        if result:
            stmt = stmt.where(AuditLog.result == result)
        if since:
            stmt = stmt.where(AuditLog.created_at >= since)
        if until:
            stmt = stmt.where(AuditLog.created_at <= until)
        return stmt
