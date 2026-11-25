"""RBAC — 三级角色权限查表。

角色矩阵（Java Security 的 hasRole / hasAuthority）：

| 权限 (perm)                  | owner | admin | member |
|------------------------------|-------|-------|--------|
| tenant.read                   |  ✅   |  ✅   |  ✅    |
| tenant.update                 |  ✅   |  ❌   |  ❌    |
| user.list / user.create       |  ✅   |  ✅   |  ❌    |
| user.update / user.delete     |  ✅   |  ❌   |  ❌    |
| session.read / session.create |  ✅   |  ✅   |  ✅（仅自己）|
| session.update / session.del  |  ✅   |  ✅   |  ✅（仅自己）|
| agent.run                     |  ✅   |  ✅   |  ✅    |
| audit_logs.read               |  ✅   |  ✅   |  ❌    |

权限字符串格式：``resource.action``。
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# 静态角色 → 权限集 映射（启动时加载，只读）
# ---------------------------------------------------------------------------

_ROLE_PERMS: dict[str, frozenset[str]] = {
    "owner": frozenset({
        "tenant.read", "tenant.update",
        "user.list", "user.create", "user.update", "user.delete",
        "session.read", "session.create", "session.update", "session.delete",
        "agent.run",
        "audit_logs.read",
    }),
    "admin": frozenset({
        "tenant.read",
        "user.list", "user.create",
        "session.read", "session.create", "session.update", "session.delete",
        "agent.run",
        "audit_logs.read",
    }),
    "member": frozenset({
        "tenant.read",
        "session.read", "session.create", "session.update", "session.delete",
        "agent.run",
    }),
}


def has_permission(role: str, permission: str) -> bool:
    """检查角色是否拥有某权限。

    Args:
        role: owner | admin | member（未知角色一律拒绝）。
        permission: 权限字符串，如 "agent.run"。

    Returns:
        True 有权限。未知角色返回 False。
    """
    perms = _ROLE_PERMS.get(role)
    if perms is None:
        return False
    return permission in perms


def role_permissions(role: str) -> frozenset[str]:
    """返回角色的完整权限集（给 /auth/me 接口用）。"""
    return _ROLE_PERMS.get(role, frozenset())


def role_hierarchy() -> list[str]:
    """角色从高到低排列。"""
    return ["owner", "admin", "member"]


__all__ = ["has_permission", "role_permissions", "role_hierarchy"]
