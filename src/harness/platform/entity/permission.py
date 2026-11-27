"""权限体系实体 — user_roles / role_page_permissions（W4.1-WEB-01）。

UserRole：用户 ↔ 角色多对多，一个用户可挂多个角色，页面权限取并集。
    users.role 保留为"主角色"（取权限最高的角色，兼容现有 require_role）。
RolePagePermission：角色 × 页面可见性矩阵（管理员可配置），租户隔离。
"""

from __future__ import annotations

from datetime import datetime, timezone

try:
    from sqlmodel import Field, SQLModel, UniqueConstraint  # type: ignore
except Exception:  # noqa: BLE001
    def Field(*a, **kw): ...  # type: ignore[misc]

    class SQLModel:  # type: ignore[no-redef]
        def __init_subclass__(cls, **kw): ...

    def UniqueConstraint(*a, **kw): ...  # type: ignore[misc]


class UserRole(SQLModel, table=True):  # noqa: F811
    """用户角色关联（多角色）。唯一约束 (user_id, role)。"""

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role", name="ux_user_roles_user_role"),)

    id: str = Field(primary_key=True, max_length=36)
    user_id: str = Field(index=True, max_length=36)
    role: str = Field(max_length=16)  # owner / admin / member
    tenant_id: str = Field(index=True, max_length=36)
    created_by: str = Field(default="", max_length=36)  # 操作人
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RolePagePermission(SQLModel, table=True):  # noqa: F811
    """角色 × 页面可见性矩阵。唯一约束 (tenant_id, role, page_key)。"""

    __tablename__ = "role_page_permissions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "role", "page_key", name="ux_role_page_tenant_role_page"
        ),
    )

    id: str = Field(primary_key=True, max_length=36)
    tenant_id: str = Field(index=True, max_length=36)
    role: str = Field(max_length=16)
    page_key: str = Field(max_length=32)
    allowed: bool = Field(default=True)
    updated_by: str = Field(default="", max_length=36)  # 最近修改人
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


__all__ = ["RolePagePermission", "UserRole"]
