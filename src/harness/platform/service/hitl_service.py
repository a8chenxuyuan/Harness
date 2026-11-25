"""HITL（人机协作）应用服务。

桥接 HTTP /api/v1/hitl/* 和 harness.integrations.hitl.HitlManager。
"""

from __future__ import annotations

from typing import Any


class HitlService:
    """HITL 审批流程的业务编排。"""

    def __init__(self) -> None:
        # 单例实例（GatewayServer 启动时可能已注入）
        self._manager = None

    @property
    def manager(self) -> Any:
        if self._manager is None:
            from harness.integrations.hitl import HitlManager
            self._manager = HitlManager()
        return self._manager

    async def approve(self, request_id: str, reason: str = "approved") -> Any:
        """批准挂起请求。"""
        return await self.manager.approve(request_id, reason=reason)

    async def deny(self, request_id: str, reason: str = "denied") -> Any:
        """拒绝挂起请求。"""
        return await self.manager.deny(request_id, reason=reason)
