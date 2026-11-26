"""UserRepository — 用户表的数据访问。⚠️ SQLModel 延迟加载。"""

from __future__ import annotations

from .repository_base import BaseRepository


class UserRepository(BaseRepository):
    """用户表 CRUD。"""

    # model 在 __init__ 里延迟绑定（因为 SQLModel 可能 C 扩展被阻止）
    model = None  # type: ignore

    def __init__(self, session) -> None:
        from harness.platform.entity.user import User
        self.model = User
        super().__init__(session)

    # ------------------------------------------------------------------
    # 业务查询
    # ------------------------------------------------------------------

    async def get_by_username(self, tenant_id: str, username: str):
        """按租户 + 登录名查用户（登录流程用）。"""
        from sqlmodel import select
        User = self.model
        result = await self.session.exec(
            select(User).where(
                User.tenant_id == tenant_id,
                User.username == username,
                User.is_active == True,  # noqa: E712
            )
        )
        return result.first()

    async def list_by_tenant(self, tenant_id: str):
        """列出租户下所有用户。"""
        from sqlmodel import select
        User = self.model
        result = await self.session.exec(
            select(User).where(User.tenant_id == tenant_id)
        )
        return list(result.all())
