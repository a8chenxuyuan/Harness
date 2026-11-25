"""Harness 数据库引擎层。

⚠️ SQLAlchemy / SQLModel 是**可选依赖** —— Windows 应用程序控制策略可能阻止
Cython 扩展 DLL 加载。这种情况下本模块仍然可以被 import，真正要用的时候才报错。
"""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 模块级单例（延迟构造）
# ---------------------------------------------------------------------------

_engine = None
_session_factory = None
DEFAULT_SQLITE_URL = "sqlite+aiosqlite:///./harness.db"


def _resolve_database_url() -> str:
    import os
    env_url = os.environ.get("HARNESS_DATABASE_URL")
    if env_url:
        return env_url
    try:
        from harness.common.config.settings import Settings
        db_url = getattr(Settings(), "database_url", "")
        if db_url:
            return db_url
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_SQLITE_URL


def get_engine(database_url: str | None = None):
    """获取（或构造）全局异步引擎单例。SQLAlchemy import 延迟到这里。"""
    global _engine
    if _engine is not None:
        return _engine

    from sqlalchemy.ext.asyncio import create_async_engine

    url = database_url or _resolve_database_url()
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    _engine = create_async_engine(url, echo=False, future=True, connect_args=connect_args)
    log.info("db.engine: created async engine for %s", url.split("@")[-1])
    return _engine


def get_session_factory(database_url: str | None = None):
    """获取 async_sessionmaker 单例。

    Session 类用 SQLModel 的 AsyncSession（带 .exec() 扩展 API），
    而不是 SQLAlchemy 原生 AsyncSession。
    """
    global _session_factory
    if _session_factory is not None:
        return _session_factory

    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession

    engine = get_engine(database_url)
    _session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    return _session_factory


async def init_db(database_url: str | None = None) -> None:
    """首次启动时根据 SQLModel.metadata 建表。"""
    from sqlmodel import SQLModel
    import harness.platform.models  # noqa: F401 — 触发 metadata 注册

    engine = get_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    log.info("db.engine: tables initialized")


async def close_db() -> None:
    """关闭引擎。"""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        log.info("db.engine: disposed")


async def yield_session(database_url: str | None = None):
    """FastAPI dependency 用的 async generator。"""
    factory = get_session_factory(database_url)
    async with factory() as session:
        yield session


__all__ = [
    "get_engine",
    "get_session_factory",
    "init_db",
    "close_db",
    "yield_session",
]
