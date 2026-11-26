"""运维接口：就绪探针 + 审计查询（Phase 23）。

- ``GET /ready``：DB ``SELECT 1`` + 工具目录非空，均通过才返回 ready
- ``GET /audit-logs``：仅 owner / admin 可查，支持 action 过滤与分页
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from harness.platform.api.deps import get_current_user, get_db, require_role
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse
from harness.platform.repository.audit_repository import AuditRepository

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


@router.get("/audit-logs", response_model=ApiResponse[dict[str, Any]])
async def list_audit_logs(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    action: str | None = Query(default=None, max_length=64),
    user: UserInfo = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """分页查询本租户审计日志（owner / admin）。"""
    rows = await AuditRepository(db).list_by_tenant(
        user.tenant_id, offset=(page - 1) * size, limit=size, action=action
    )
    items = [
        {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "user_id": row.user_id,
            "session_id": row.session_id,
            "action": row.action,
            "target": row.target,
            "result": row.result,
            "detail": _safe_json(row.detail_json),
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
    return {
        "code": 0,
        "message": "ok",
        "data": {"items": items, "total": len(items), "page": page, "size": size},
    }


def _safe_json(raw: str | None) -> dict[str, Any]:
    """detail_json 解析失败时返回空 dict，不让脏数据打断查询。"""
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


__all__ = ["router"]
