"""开发环境种子数据（Phase 22）。

幂等创建：
    - 租户 ``dev-tenant``（plan=free）
    - owner 用户 ``admin`` / ``admin123``
    - member 用户 ``demo`` / ``demo1234``

注意：仅供本地开发与集成测试使用，生产环境禁止调用。
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

DEV_TENANT_ID = "dev-tenant"
DEV_USERS: tuple[tuple[str, str, str, str], ...] = (
    # (username, password, email, role)
    ("admin", "admin123", "admin@example.com", "owner"),
    ("demo", "demo1234", "demo@example.com", "member"),
)


async def seed_dev_data(session) -> dict[str, int]:
    """写入开发种子数据（幂等）。

    Args:
        session: ``harness.platform.infra.engine.get_session_factory()`` 产出的 AsyncSession。

    Returns:
        ``{"tenants": 0|1, "users": n}`` —— 本次实际新建的行数。
    """
    from sqlmodel import select

    from harness.platform.auth.password import hash_password
    from harness.platform.entity.tenant import Tenant
    from harness.platform.entity.user import User

    created = {"tenants": 0, "users": 0}

    tenant = await session.get(Tenant, DEV_TENANT_ID)
    if tenant is None:
        session.add(Tenant(id=DEV_TENANT_ID, name="Dev Tenant", plan="free", is_active=True))
        await session.commit()
        created["tenants"] = 1

    for username, password, email, role in DEV_USERS:
        result = await session.exec(
            select(User).where(
                User.tenant_id == DEV_TENANT_ID,
                User.username == username,
            )
        )
        if result.first() is not None:
            continue
        session.add(
            User(
                id=f"dev-{username}",
                tenant_id=DEV_TENANT_ID,
                username=username,
                email=email,
                hashed_password=hash_password(password),
                role=role,
                is_active=True,
            )
        )
        await session.commit()
        created["users"] += 1

    log.info("seed: dev data ready %s", created)
    return created


async def seed_default(database_url: str | None = None) -> dict[str, int]:
    """便捷入口：自建 session 并写入种子数据。"""
    from harness.platform.infra.engine import get_session_factory, init_db

    await init_db(database_url)
    factory = get_session_factory(database_url)
    async with factory() as session:
        return await seed_dev_data(session)


__all__ = ["seed_dev_data", "seed_default", "DEV_TENANT_ID", "DEV_USERS"]
