"""运维接口：就绪探针 + 审计查询 / 导出（Phase 23）。

- ``GET /ready``：DB ``SELECT 1`` + 工具目录非空，均通过才返回 ready
- ``GET /audit-logs``：仅 owner / admin 可查，支持动作 / 用户 / 会话 / 结果 / 时间过滤与分页
- ``GET /audit-logs/actions``：筛选下拉用的动作枚举
- ``GET /audit-logs/export``：按当前过滤条件导出 CSV
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from harness.platform.api.deps import get_current_user, get_db, require_role
from harness.platform.api.vo.audit_vo import AuditLogListResponse
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse
from harness.platform.api.vo.metrics_vo import MetricsSummary
from harness.platform.service.audit_service import AuditService

router = APIRouter(tags=["observability"])


@router.get("/ready", response_model=ApiResponse[dict[str, Any]])
async def ready(
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """就绪探针：数据库可执行查询 + 工具目录非空。"""
    from sqlalchemy import text

    from harness.platform.api.v1.tools import tool_catalog

    try:
        await db.exec(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"database not ready: {exc}") from exc

    tools = tool_catalog()
    if not tools:
        raise HTTPException(status_code=503, detail="tool catalog empty")

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "status": "ready",
            "checks": {"database": "ok", "tools": len(tools)},
        },
    }


@router.get("/observability/metrics", response_model=ApiResponse[MetricsSummary])
async def metrics_summary(
    user: UserInfo = Depends(require_role("owner", "admin")),
) -> dict[str, Any]:
    """HTTP 指标摘要：请求量、错误率、延迟分位与最近错误。"""
    from harness.common.observability.metrics import metrics_snapshot

    return {"code": 0, "message": "ok", "data": metrics_snapshot()}


@router.get("/audit-logs", response_model=ApiResponse[AuditLogListResponse])
async def list_audit_logs(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    action: str | None = Query(default=None, max_length=64),
    user_id: str | None = Query(default=None, max_length=36),
    session_id: str | None = Query(default=None, max_length=64),
    result: str | None = Query(default=None, max_length=16),
    since: datetime | None = Query(default=None, description="起始时间（ISO-8601）"),
    until: datetime | None = Query(default=None, description="结束时间（ISO-8601）"),
    user: UserInfo = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """分页查询本租户审计日志（owner / admin）。"""
    data = await AuditService(user, db).list_logs(
        page=page,
        size=size,
        action=action,
        user_id=user_id,
        session_id=session_id,
        result=result,
        since=since,
        until=until,
    )
    return {"code": 0, "message": "ok", "data": data}


@router.get("/audit-logs/actions", response_model=ApiResponse[list[str]])
async def list_audit_actions(
    user: UserInfo = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """本租户出现过的审计动作标识（用于筛选下拉）。"""
    actions = await AuditService(user, db).list_actions()
    return {"code": 0, "message": "ok", "data": actions}


@router.get("/audit-logs/export")
async def export_audit_logs(
    action: str | None = Query(default=None, max_length=64),
    user_id: str | None = Query(default=None, max_length=36),
    session_id: str | None = Query(default=None, max_length=64),
    result: str | None = Query(default=None, max_length=16),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    user: UserInfo = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """按过滤条件导出审计日志 CSV（最多 5000 行，UTF-8 BOM）。"""
    csv_text = await AuditService(user, db).export_csv(
        action=action,
        user_id=user_id,
        session_id=session_id,
        result=result,
        since=since,
        until=until,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    filename = f"audit-logs-{stamp}.csv"
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = ["router"]
