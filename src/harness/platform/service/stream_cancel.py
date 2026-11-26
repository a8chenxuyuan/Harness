"""流式运行取消 — 进程内取消标记 + 无活跃流时的数据库收尾。

SSE 采用协作式取消：登记标记后由 ``ChatStreamService.stream`` 在下一个事件
前停止生成并落终态。进程内没有活跃流（服务重启 / 已断线）时，直接把运行
记录与残留的 streaming 消息置为 cancelled，避免出现悬挂消息。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from harness.platform.api.exceptions import BizError
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.entity.agent_run import AgentRun
from harness.platform.repository.agent_run_repository import AgentRunRepository
from harness.platform.repository.session_message_repository import (
    SessionMessageRepository,
)

# 取消标记存活时长（秒）：防止异常路径漏 release 导致内存无限增长
_TTL_SECONDS = 3600.0

# 运行记录终态：命中后不再接受取消请求
_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


class StreamCancelRegistry:
    """run_id → 登记时间 / 取消标记 的进程内注册表。"""

    def __init__(self) -> None:
        self._registered: dict[str, float] = {}
        self._cancelled: set[str] = set()

    def register(self, run_id: str) -> None:
        """登记一个即将开始的流式运行（顺带清理过期标记）。"""
        self._purge()
        self._registered[run_id] = time.monotonic()

    def request(self, run_id: str) -> bool:
        """登记取消请求；该 run 不在本进程活跃流中时返回 False。"""
        self._purge()
        if run_id not in self._registered:
            return False
        self._cancelled.add(run_id)
        return True

    def is_cancelled(self, run_id: str) -> bool:
        """该 run 是否已被请求取消。"""
        return run_id in self._cancelled

    def release(self, run_id: str) -> None:
        """流结束后清理标记。"""
        self._registered.pop(run_id, None)
        self._cancelled.discard(run_id)

    def _purge(self) -> None:
        """清理超过 TTL 的登记（异常路径兜底）。"""
        deadline = time.monotonic() - _TTL_SECONDS
        expired = [key for key, at in self._registered.items() if at < deadline]
        for key in expired:
            self.release(key)


_registry: StreamCancelRegistry | None = None


def get_stream_cancel_registry() -> StreamCancelRegistry:
    """获取全局取消注册表单例。"""
    global _registry
    if _registry is None:
        _registry = StreamCancelRegistry()
    return _registry


def reset_stream_cancel_registry() -> None:
    """重置单例（仅供测试）。"""
    global _registry
    _registry = None


class StreamCancelService:
    """取消流式运行的用例：校验归属、登记取消、无活跃流时兜底收尾。"""

    def __init__(self, user: UserInfo, db) -> None:
        self.user = user
        self.db = db
        self.runs = AgentRunRepository(db)
        self.messages = SessionMessageRepository(db)

    async def cancel(self, run_id: str) -> dict[str, str]:
        """请求取消指定运行。

        Returns:
            ``{"run_id", "status"}``；``cancelling`` 表示已通知活跃流，
            其余为运行记录当前（或兜底后的）状态。
        """
        record = await self.runs.get_by_owner(
            self.user.tenant_id, self.user.user_id, run_id
        )
        if record is None:
            raise BizError(404, f"run {run_id} not found")
        if record.status in _TERMINAL:
            return {"run_id": run_id, "status": record.status}

        if get_stream_cancel_registry().request(run_id):
            return {"run_id": run_id, "status": "cancelling"}

        await self._settle_orphan(record)
        return {"run_id": run_id, "status": "cancelled"}

    async def _settle_orphan(self, record: AgentRun) -> None:
        """无活跃流时兜底：运行记录与残留 streaming 消息一起置 cancelled。"""
        now = datetime.now(timezone.utc)
        record.status = "cancelled"
        record.error = "用户取消"
        record.finished_at = now
        record.updated_at = now
        await self.runs.save(record)

        if not record.session_id:
            return
        pending = await self.messages.list_streaming(
            self.user.tenant_id, record.session_id
        )
        for message in pending:
            message.status = "cancelled"
            await self.messages.save(message)


__all__ = [
    "StreamCancelRegistry",
    "StreamCancelService",
    "get_stream_cancel_registry",
    "reset_stream_cancel_registry",
]
