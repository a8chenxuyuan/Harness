"""权限体系服务 — 角色并集、页面矩阵、用户角色分配（W4.1-WEB-01）。

核心语义：
    - 一个用户可挂多个角色（user_roles 表），页面权限 = 所有角色
      allowed_pages 的**并集**；
    - users.role 保留为"主角色"（取权限最高角色），兼容现有
      require_role 接口鉴权；
    - owner 在代码层强制全量可见（矩阵里不存 owner 行，防配置锁死）；
    - 矩阵缺失时按 DEFAULT_MATRIX 播种（幂等，SQLite/PG 双兼容）；
    - 进程内缓存，写操作即失效（单实例足够；多实例换 Redis）。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlmodel import select

from harness.platform.entity.permission import RolePagePermission, UserRole

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量：角色体系 / 页面清单 / 默认矩阵
# ---------------------------------------------------------------------------

ROLE_LEVELS = {"machine": 0, "member": 1, "admin": 2, "owner": 3}
ASSIGNABLE_ROLES = ("owner", "admin", "member")

# 页面清单（与前端路由 meta.pageKey 对齐）
# 用户区：home/sessions/tasks/automation/connections/memories
# 管理端：overview/agent/skills/tools/api-keys/webhooks/audit/observability/permissions
PAGE_KEYS: tuple[str, ...] = (
    "home",
    "sessions",
    "tasks",
    "automation",
    "connections",
    "memories",
    "overview",
    "agent",
    "skills",
    "tools",
    "api-keys",
    "webhooks",
    "plans",
    "worker",
    "audit",
    "observability",
    "settings",
    "permissions",
)

# 默认矩阵：member 只见 C 端用户区；admin 全量；owner 代码层保底全量
DEFAULT_MATRIX: dict[str, set[str]] = {
    "member": {
        "home",
        "sessions",
        "tasks",
        "automation",
        "connections",
        "memories",
    },
    "admin": set(PAGE_KEYS),
}

# 进程内缓存：user_id -> allowed pages；tenant_id -> 矩阵
_pages_cache: dict[str, frozenset[str]] = {}
_matrix_cache: dict[str, dict[str, dict[str, bool]]] = {}


def invalidate_cache(user_id: str | None = None, tenant_id: str | None = None) -> None:
    """写操作后失效缓存。"""
    if user_id:
        _pages_cache.pop(user_id, None)
    if tenant_id:
        _matrix_cache.pop(tenant_id, None)


def highest_role(roles: list[str]) -> str:
    """取权限最高的角色（写回 users.role 主角色用）。"""
    best = "member"
    for r in roles:
        if ROLE_LEVELS.get(r, 0) > ROLE_LEVELS.get(best, 0):
            best = r
    return best


# ---------------------------------------------------------------------------
# 矩阵读取 / 播种
# ---------------------------------------------------------------------------

async def _load_matrix(session, tenant_id: str) -> dict[str, dict[str, bool]]:
    """读矩阵（带缓存）；空库播种默认矩阵。"""
    cached = _matrix_cache.get(tenant_id)
    if cached is not None:
        return cached

    existing = (await session.exec(
        select(RolePagePermission).where(RolePagePermission.tenant_id == tenant_id)
    )).all()
    if not existing:
        await seed_default_matrix(session, tenant_id)
        existing = (await session.exec(
            select(RolePagePermission).where(RolePagePermission.tenant_id == tenant_id)
        )).all()

    matrix: dict[str, dict[str, bool]] = {}
    for row in existing:
        matrix.setdefault(row.role, {})[row.page_key] = row.allowed

    # 老库平滑补种：已有矩阵缺新页面行时按默认值补齐（不覆盖已有行，
    # 保留管理员自定义）。例如 W4.1-WEB-02 新增的 home/tasks/automation。
    added = False
    for role, pages in DEFAULT_MATRIX.items():
        for page_key in PAGE_KEYS:
            if page_key not in matrix.get(role, {}):
                session.add(
                    RolePagePermission(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        role=role,
                        page_key=page_key,
                        allowed=page_key in pages,
                    )
                )
                matrix.setdefault(role, {})[page_key] = page_key in pages
                added = True
    if added:
        await session.commit()
        log.info("permission: 租户 %s 矩阵补种新页面行", tenant_id)

    _matrix_cache[tenant_id] = matrix
    return matrix


async def seed_default_matrix(session, tenant_id: str) -> None:
    """播种默认矩阵（幂等：按唯一键跳过已存在行）。"""
    for role, pages in DEFAULT_MATRIX.items():
        for page_key in PAGE_KEYS:
            allowed = page_key in pages
            session.add(
                RolePagePermission(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    role=role,
                    page_key=page_key,
                    allowed=allowed,
                )
            )
    await session.commit()
    log.info("permission: 已为租户 %s 播种默认矩阵", tenant_id)


# ---------------------------------------------------------------------------
# 用户角色 / allowed_pages
# ---------------------------------------------------------------------------

async def get_user_roles(session, user_id: str) -> list[str]:
    """读用户全部关联角色（user_roles 表）。"""
    rows = (await session.exec(
        select(UserRole).where(UserRole.user_id == user_id)
    )).all()
    return [r.role for r in rows]


async def allowed_pages(session, tenant_id: str, user_id: str, primary_role: str) -> list[str]:
    """计算用户可见页面（多角色并集；owner 代码层保底全量）。"""
    if primary_role == "owner":
        return list(PAGE_KEYS)

    cached = _pages_cache.get(user_id)
    if cached is not None:
        return sorted(cached)

    matrix = await _load_matrix(session, tenant_id)
    roles = set(await get_user_roles(session, user_id)) | {primary_role}
    pages: set[str] = set()
    for role in roles:
        role_pages = matrix.get(role, {})
        for page_key in PAGE_KEYS:
            if role_pages.get(page_key, page_key in DEFAULT_MATRIX.get(role, set())):
                pages.add(page_key)

    _pages_cache[user_id] = frozenset(pages)
    return sorted(pages)


# ---------------------------------------------------------------------------
# 矩阵写入
# ---------------------------------------------------------------------------

async def set_page_permission(
    session, tenant_id: str, role: str, page_key: str, allowed: bool, operator_id: str
) -> dict[str, Any]:
    """设置单格矩阵；owner 行拒绝修改；返回更新后的行数据。"""
    from harness.platform.api.exceptions import BizError

    if role == "owner":
        raise BizError(400, "owner 角色为代码保底全量可见，不可配置")
    if role not in DEFAULT_MATRIX or page_key not in PAGE_KEYS:
        raise BizError(400, f"非法角色或页面: role={role}, page={page_key}")

    result = await session.exec(
        select(RolePagePermission)
        .where(RolePagePermission.tenant_id == tenant_id)
        .where(RolePagePermission.role == role)
        .where(RolePagePermission.page_key == page_key)
    )
    row = result.first()
    if row is None:
        row = RolePagePermission(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            role=role,
            page_key=page_key,
            allowed=allowed,
            updated_by=operator_id,
        )
    else:
        row.allowed = allowed
        row.updated_by = operator_id
    session.add(row)
    await session.commit()
    invalidate_cache(tenant_id=tenant_id)
    return {"role": role, "page_key": page_key, "allowed": allowed}


# ---------------------------------------------------------------------------
# 用户角色分配
# ---------------------------------------------------------------------------

async def set_user_roles(
    session, tenant_id: str, target_user_id: str, roles: list[str], operator_id: str
) -> dict[str, Any]:
    """全量替换用户角色列表，并同步 users.role 主角色（取最高）。

    Returns:
        {"user_id", "roles", "primary_role"}
    """
    from harness.platform.api.exceptions import BizError
    from harness.platform.auth.audit import record_audit
    from harness.platform.entity.user import User
    from harness.platform.repository.user_repository import UserRepository

    if not roles:
        raise BizError(400, "至少保留一个角色")
    bad = [r for r in roles if r not in ASSIGNABLE_ROLES]
    if bad:
        raise BizError(400, f"不可分配的角色: {bad}")

    users = UserRepository(session)
    user = await users.get(target_user_id)
    if user is None or user.tenant_id != tenant_id:
        raise BizError(404, f"用户 {target_user_id} 不存在")

    # 全量替换（删旧插新）
    old_rows = (await session.exec(
        select(UserRole).where(UserRole.user_id == target_user_id)
    )).all()
    for row in old_rows:
        await session.delete(row)
    for role in dict.fromkeys(roles):  # 去重保序
        session.add(
            UserRole(
                id=str(uuid.uuid4()),
                user_id=target_user_id,
                role=role,
                tenant_id=tenant_id,
                created_by=operator_id,
            )
        )
    # 同步主角色（最高权限），保持 require_role 兼容
    primary = highest_role(roles)
    user.role = primary
    session.add(user)
    await session.commit()

    invalidate_cache(user_id=target_user_id)
    await record_audit(
        session,
        tenant_id=tenant_id,
        user_id=operator_id,
        action="permission.user_roles.set",
        target=target_user_id,
        result="success",
        detail={"roles": roles, "previous": [r.role for r in old_rows]},
    )
    return {"user_id": target_user_id, "roles": list(dict.fromkeys(roles)), "primary_role": primary}


async def list_users_with_roles(session, tenant_id: str) -> list[dict[str, Any]]:
    """列出租户全部用户及角色（权限管理页用）。"""
    from harness.platform.entity.user import User

    users = (await session.exec(
        select(User).where(User.tenant_id == tenant_id).order_by(User.created_at)
    )).all()
    roles_map: dict[str, list[str]] = {}
    for row in (await session.exec(
        select(UserRole).where(UserRole.tenant_id == tenant_id)
    )).all():
        roles_map.setdefault(row.user_id, []).append(row.role)

    return [
        {
            "user_id": u.id,
            "username": u.username,
            "email": u.email,
            "primary_role": u.role,
            "roles": sorted(set(roles_map.get(u.id, [u.role]))),
            "is_active": u.is_active,
        }
        for u in users
    ]


__all__ = [
    "ASSIGNABLE_ROLES",
    "DEFAULT_MATRIX",
    "PAGE_KEYS",
    "ROLE_LEVELS",
    "allowed_pages",
    "get_user_roles",
    "highest_role",
    "invalidate_cache",
    "list_users_with_roles",
    "seed_default_matrix",
    "set_page_permission",
    "set_user_roles",
]
