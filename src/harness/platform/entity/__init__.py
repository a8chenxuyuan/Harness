"""Harness 数据库实体层（SQLModel table=True）。

显式导入 5 个子模块，确保 ``import harness.platform.entity`` 时
所有 table=True 实体都完成 ``SQLModel.metadata`` 注册——
这是 ``db.engine.init_db()`` 里 ``metadata.create_all`` 能建表的前提。

子模块自身对 SQLModel 缺失做了 stub 兜底，因此本文件在无 C 扩展的
环境下也能 import 成功。
"""

from __future__ import annotations

from harness.platform.entity.agent_run import AgentRun
from harness.platform.entity.api_key import ApiKey
from harness.platform.entity.audit_log import AuditLog
from harness.platform.entity.channel import ChannelApp, ChannelBinding
from harness.platform.entity.idempotency_key import IdempotencyRecord
from harness.platform.entity.memory import MemoryEntry
from harness.platform.entity.plan import PlanRecord
from harness.platform.entity.refresh_token import RefreshToken
from harness.platform.entity.session import SessionRecord
from harness.platform.entity.session_message import SessionMessage
from harness.platform.entity.tenant import Tenant
from harness.platform.entity.tenant_quota import TenantQuota, TenantUsageDaily
from harness.platform.entity.user import User
from harness.platform.entity.webhook import WebhookDelivery, WebhookSubscription

__all__ = [
    "Tenant",
    "User",
    "ApiKey",
    "ChannelApp",
    "ChannelBinding",
    "WebhookSubscription",
    "WebhookDelivery",
    "SessionRecord",
    "SessionMessage",
    "AgentRun",
    "AuditLog",
    "MemoryEntry",
    "PlanRecord",
    "IdempotencyRecord",
    "TenantQuota",
    "TenantUsageDaily",
    "RefreshToken",
]
