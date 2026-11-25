"""审计日志接线层（Phase 22）。

薄封装 ``AuditRepository``，并保证**审计写入失败不阻塞主流程**——
与 roadmap「审计不阻塞 run_loop」一致：异常只打 warning。

用法::

    await record_audit(db, tenant_id=..., user_id=..., action="auth.login", target="alice")
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


async def record_audit(
    session,
    *,
    tenant_id: str,
    user_id: str,
    action: str,
    target: str = "",
    result: str = "success",
    session_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """写一条审计日志；任何失败都只记录 warning，不向上抛。

    Args:
        session: 当前请求的 AsyncSession（``Depends(get_db)`` 注入）。
        tenant_id: 租户 id。
        user_id: 操作者 id。
        action: 动作标识，如 ``auth.login`` / ``agent.run``。
        target: 操作对象（用户名 / 工具名 / plan_id 等）。
        result: success | denied | error。
        session_id: 关联会话 id，可空。
        detail: 附加详情，序列化后写入 detail 列。
    """
    try:
        from harness.platform.repository.audit_repo import AuditRepository

        await AuditRepository(session).log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            target=target,
            result=result,
            session_id=session_id,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
    except Exception:  # noqa: BLE001 — 审计失败绝不影响主流程
        log.warning("audit: 写入失败 action=%s tenant=%s", action, tenant_id, exc_info=True)


__all__ = ["record_audit"]
