"""审计查询服务 — 过滤、分页、动作枚举与 CSV 导出。

只读：审计表 append-only，本服务不修改任何记录。
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from harness.platform.api.vo.audit_vo import AuditLogItem, AuditLogListResponse
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.repository.audit_repository import AuditRepository

# 单次导出上限：避免一次拉爆内存 / 连接
MAX_EXPORT_ROWS = 5000

_CSV_HEADER = ["时间", "动作", "结果", "用户", "会话", "目标", "详情"]


class AuditService:
    """租户内审计日志的查询与导出用例。"""

    def __init__(self, user: UserInfo, db) -> None:
        self.user = user
        self.repo = AuditRepository(db)

    async def list_logs(
        self,
        *,
        page: int = 1,
        size: int = 20,
        action: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        result: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> AuditLogListResponse:
        """按条件分页查询本租户审计日志。"""
        rows = await self.repo.list_by_tenant(
            self.user.tenant_id,
            offset=(page - 1) * size,
            limit=size,
            action=action,
            user_id=user_id,
            session_id=session_id,
            result=result,
            since=since,
            until=until,
        )
        total = await self.repo.count_by_tenant(
            self.user.tenant_id,
            action=action,
            user_id=user_id,
            session_id=session_id,
            result=result,
            since=since,
            until=until,
        )
        return AuditLogListResponse(
            items=[_to_item(row) for row in rows],
            total=total,
            page=page,
            size=size,
        )

    async def list_actions(self) -> list[str]:
        """本租户出现过的动作标识（筛选下拉用）。"""
        return await self.repo.list_actions(self.user.tenant_id)

    async def export_csv(
        self,
        *,
        action: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        result: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> str:
        """按条件导出 CSV（UTF-8 BOM，Excel 可直接打开）。"""
        rows = await self.repo.list_by_tenant(
            self.user.tenant_id,
            offset=0,
            limit=MAX_EXPORT_ROWS,
            action=action,
            user_id=user_id,
            session_id=session_id,
            result=result,
            since=since,
            until=until,
        )
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(_CSV_HEADER)
        for row in rows:
            writer.writerow(
                [
                    _iso_utc(row.created_at),
                    row.action,
                    row.result,
                    row.user_id,
                    row.session_id or "",
                    row.target,
                    row.detail_json,
                ]
            )
        return "\ufeff" + buffer.getvalue()


def _to_item(row) -> AuditLogItem:
    """实体 → VO：解析 detail、统一 UTC 时间。"""
    return AuditLogItem(
        id=int(row.id or 0),
        user_id=row.user_id,
        session_id=row.session_id,
        action=row.action,
        target=row.target,
        result=row.result,
        detail=_safe_json(row.detail_json),
        created_at=_iso_utc(row.created_at),
    )


def _safe_json(raw: str | None) -> dict[str, Any]:
    """detail 解析失败返回空 dict，脏数据不打断查询。"""
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _iso_utc(value: datetime) -> str:
    """SQLite 取出的 naive 时间按 UTC 处理，统一输出带 Z 的 ISO 串。"""
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = ["AuditService", "MAX_EXPORT_ROWS"]
