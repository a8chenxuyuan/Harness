"""AgentRunRepository — 运行记录表的数据访问。⚠️ SQLModel 延迟加载。"""

from __future__ import annotations

from .repository_base import BaseRepository


class AgentRunRepository(BaseRepository):
    """运行记录的写入与按用户查询。"""

    model = None  # type: ignore

    def __init__(self, session) -> None:
        from harness.platform.entity.agent_run import AgentRun
        self.model = AgentRun
        super().__init__(session)

    async def list_by_user(
        self,
        tenant_id: str,
        user_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
        status: str | None = None,
    ):
        """按租户 + 用户分页列出运行记录（创建时间倒序）。"""
        from sqlmodel import select
        Record = self.model
        stmt = select(Record).where(
            Record.tenant_id == tenant_id,
            Record.user_id == user_id,
        )
        if status:
            stmt = stmt.where(Record.status == status)
        result = await self.session.exec(
            stmt.order_by(Record.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.all())

    async def count_by_user(
        self, tenant_id: str, user_id: str, *, status: str | None = None
    ) -> int:
        """按租户 + 用户统计运行记录数。"""
        from sqlalchemy import func, select
        Record = self.model
        stmt = select(func.count()).select_from(Record).where(
            Record.tenant_id == tenant_id,
            Record.user_id == user_id,
        )
        if status:
            stmt = stmt.where(Record.status == status)
        result = await self.session.exec(stmt)
        rows = result.all()
        if not rows:
            return 0
        value = rows[0]
        return int(value) if isinstance(value, (int, float)) else int(value[0])

    async def get_by_owner(self, tenant_id: str, user_id: str, run_id: str):
        """按 run_id + 租户 + 发起人查询。"""
        from sqlmodel import select
        Record = self.model
        result = await self.session.exec(
            select(Record).where(
                Record.run_id == run_id,
                Record.tenant_id == tenant_id,
                Record.user_id == user_id,
            )
        )
        return result.first()

    async def count_active(self, tenant_id: str) -> int:
        """统计租户当前活跃运行数（queued / running）。"""
        from sqlalchemy import func, select

        Record = self.model
        result = await self.session.exec(
            select(func.count()).select_from(Record).where(
                Record.tenant_id == tenant_id,
                Record.status.in_(("queued", "running")),  # type: ignore[attr-defined]
            )
        )
        rows = result.all()
        if not rows:
            return 0
        value = rows[0]
        return int(value) if isinstance(value, (int, float)) else int(value[0])

    async def mark_statuses(
        self, from_status: str, to_status: str, *, error: str | None = None
    ) -> int:
        """批量把 ``from_status`` 的运行改为 ``to_status``，返回影响行数。

        启动恢复用：进程重启后 running 记录已不可能继续执行，统一标记
        interrupted，避免列表长期展示「运行中」。
        """
        from datetime import datetime, timezone
        from sqlalchemy import update

        Record = self.model
        values: dict = {
            "status": to_status,
            "updated_at": datetime.now(timezone.utc),
            "finished_at": datetime.now(timezone.utc),
        }
        if error is not None:
            values["error"] = error
        result = await self.session.exec(
            update(Record).where(Record.status == from_status).values(**values)
        )
        await self.session.commit()
        return int(result.rowcount or 0)
