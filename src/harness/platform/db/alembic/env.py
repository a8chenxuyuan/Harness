"""Alembic 迁移环境 — Phase 24。

这个文件被 Alembic CLI import，用来：
    1. 从 Settings 或环境变量取 DATABASE_URL
    2. 把 SQLModel.metadata 注册到 target_metadata
    3. 配置 run_migrations_online / run_migrations_offline

运行方式（项目根目录）::

    # 先确保所有 entity 被 import（metadata 才注册）
    python -c "import harness.platform.models"

    # 生成迁移脚本（自动比对 metadata 和现有表）
    alembic revision --autogenerate -m "initial tables"

    # 执行升级
    alembic upgrade head
"""

from __future__ import annotations

import logging
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# 1. 读取 alembic.ini 的 logging 配置
# ---------------------------------------------------------------------------
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

log = logging.getLogger("alembic")

# ---------------------------------------------------------------------------
# 2. 把所有 entity 注册到 SQLModel.metadata
# ---------------------------------------------------------------------------
from sqlmodel import SQLModel  # noqa: E402

import harness.platform.models  # noqa: F401,E402 — 触发 metadata 注册
target_metadata = SQLModel.metadata

# ---------------------------------------------------------------------------
# 3. 解析 DATABASE_URL（优先级：env → Settings → alembic.ini 占位 → 默认 SQLite）
# ---------------------------------------------------------------------------


def _resolve_url() -> str:
    # a) alembic.ini 里 sqlalchemy.url 如果有值，直接用
    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url:
        return ini_url

    # b) 环境变量
    env_url = os.environ.get("HARNESS_DATABASE_URL")
    if env_url:
        return env_url

    # c) Settings
    try:
        from harness.common.config.settings import Settings
        s = Settings()
        if s.database_url:
            return s.database_url
    except Exception:  # noqa: BLE001
        pass

    # d) 默认 SQLite
    return "sqlite:///./harness.db"


# Alembic 期望 sync driver，把 async+aiosqlite 换成 sqlite://
def _to_sync_url(async_url: str) -> str:
    if async_url.startswith("sqlite+aiosqlite:///"):
        return async_url.replace("sqlite+aiosqlite:///", "sqlite:///", 1)
    if async_url.startswith("sqlite+aiosqlite://"):
        return async_url.replace("sqlite+aiosqlite://", "sqlite://", 1)
    # PostgreSQL async → sync（psycopg → psycopg2 或保持 psycopg）
    if "+asyncpg" in async_url:
        return async_url.replace("+asyncpg", "")
    if "+psycopg" in async_url:
        return async_url.replace("+psycopg", "+psycopg2")
    return async_url


DATABASE_URL = _to_sync_url(_resolve_url())
config.set_main_option("sqlalchemy.url", DATABASE_URL)
log.info("alembic.env: using DATABASE_URL = %s", DATABASE_URL.split("@")[-1])


# ---------------------------------------------------------------------------
# 4. offline 模式（不连 DB，生成 .sql 脚本）
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# 5. online 模式（真正连 DB 执行）
# ---------------------------------------------------------------------------


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connect_args: dict = {}
    if DATABASE_URL.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
