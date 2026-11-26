"""PlanRepository — plans 表的数据访问（Phase 23/24）。"""

from __future__ import annotations

from typing import Any

from harness.platform.entity.plan import PlanRecord


class PlanRepository:
    """计划表 CRUD（租户隔离）。"""

    def __init__(self, session) -> None:
        self.session = session

    async def save(self, record: PlanRecord) -> PlanRecord:
        """新增或更新一条计划。"""
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_by_id(self, tenant_id: str, plan_id: str) -> PlanRecord | None:
        """按 plan_id + 租户隔离查询。"""
        from sqlmodel import select

        result = await self.session.exec(
            select(PlanRecord).where(
                PlanRecord.plan_id == plan_id,
                PlanRecord.tenant_id == tenant_id,
            )
        )
        return result.first()

    async def list_by_tenant(
        self, tenant_id: str, *, offset: int = 0, limit: int = 20
    ) -> list[PlanRecord]:
        """按租户分页列出计划（创建时间倒序）。"""
        from sqlmodel import select

        result = await self.session.exec(
            select(PlanRecord)
            .where(PlanRecord.tenant_id == tenant_id)
            .order_by(PlanRecord.created_at.desc())  # type: ignore[attr-defined]
            .offset(offset)
            .limit(limit)
        )
        return list(result.all())

    async def count_by_tenant(self, tenant_id: str) -> int:
        """租户下计划总数。"""
        from sqlalchemy import func, select

        result = await self.session.exec(
            select(func.count()).select_from(PlanRecord).where(
                PlanRecord.tenant_id == tenant_id
            )
        )
        return _count_of(result.all())

    async def mark_statuses(self, from_status: str, to_status: str) -> int:
        """批量把 ``from_status`` 的计划改为 ``to_status``，返回影响行数。

        启动恢复用：后台执行随进程终止，running 计划统一标记 interrupted。
        """
        from datetime import datetime, timezone
        from sqlalchemy import update

        result = await self.session.exec(
            update(PlanRecord)
            .where(PlanRecord.status == from_status)
            .values(status=to_status, updated_at=datetime.now(timezone.utc))
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    async def update_status(self, record: PlanRecord, status: str) -> PlanRecord:
        """更新执行状态（running / done / failed / cancelled）。"""
        from datetime import datetime, timezone

        record.status = status
        record.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        return record

    @staticmethod
    def to_dict(record: PlanRecord) -> dict[str, Any]:
        """转成可 JSON 序列化的摘要字典。"""
        import json

        try:
            steps = json.loads(record.steps_json or "[]")
        except json.JSONDecodeError:
            steps = []
        return {
            "plan_id": record.plan_id,
            "goal": record.goal,
            "steps": steps,
            "plan_hash": record.plan_hash,
            "approved": record.approved,
            "status": record.status,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        }


__all__ = ["PlanRepository"]


def _count_of(rows: list) -> int:
    """从 ``select(func.count())`` 的结果行里取整数（兼容 Row / 标量）。"""
    if not rows:
        return 0
    value = rows[0]
    if isinstance(value, (int, float)):
        return int(value)
    return int(value[0])
