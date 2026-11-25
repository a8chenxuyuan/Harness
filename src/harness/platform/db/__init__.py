"""Harness 数据库基础设施（引擎 + Alembic 迁移）。

⚠️ SQLModel / SQLAlchemy 是可选依赖 —— 某些机器上 Windows 应用程序控制策略
会阻止 Cython 扩展 DLL 加载。这种情况下 import 本包不会炸，直接用 Phase 0-21
引擎层 + Phase 23 HTTP 接口层；DB 相关功能（Repository / init_db）需要时才会报错。
"""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    """延迟加载 db.engine 成员。"""
    # 这样顶层 ``from harness.platform.db import init_db`` 不会在模块 import 时
    # 立即触发 sqlalchemy / sqlmodel 的 C 扩展加载
    from . import engine as _engine
    if not hasattr(_engine, name):
        raise AttributeError(f"module 'harness.platform.db' has no attribute {name!r}")
    return getattr(_engine, name)


__all__ = [
    "get_engine",
    "get_session_factory",
    "init_db",
    "close_db",
    "yield_session",
]
