"""Harness 数据库实体层（SQLModel table=True）。

显式导入 5 个子模块，确保 ``import harness.platform.models`` 时
所有 table=True 实体都完成 ``SQLModel.metadata`` 注册——
这是 ``db.engine.init_db()`` 里 ``metadata.create_all`` 能建表的前提。

子模块自身对 SQLModel 缺失做了 stub 兜底，因此本文件在无 C 扩展的
环境下也能 import 成功。
"""

from __future__ import annotations

from harness.platform.models.audit_log import AuditLog
from harness.platform.models.memory import MemoryEntry
from harness.platform.models.plan import PlanRecord
from harness.platform.models.session import SessionRecord
from harness.platform.models.tenant import Tenant
from harness.platform.models.user import User

__all__ = [
    "Tenant",
    "User",
    "SessionRecord",
    "AuditLog",
    "MemoryEntry",
    "PlanRecord",
]
