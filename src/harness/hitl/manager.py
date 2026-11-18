"""HITL（Human-In-The-Loop）请求管理。

HitlManager 挂起需要人工确认的工具调用：
  1. request_approval 生成 pending 记录，返回 request_id
  2. 外部（CLI / Webhook / 管理面）调用 approve / deny 写入决策
  3. wait_for_decision 用 asyncio.Event 等待决策落盘后返回

HitlSession 是 frozen dataclass，承载一次待人工决策的完整上下文。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

log = logging.getLogger(__name__)

Decision = Literal["allow", "deny", "ask"]
Status = Literal["pending", "approved", "denied", "expired"]


@dataclass(frozen=True)
class HitlSession:
    """一次等待人工确认的 HITL 会话。

    Attributes:
        request_id: 请求唯一 id。
        tool_name: 被请求执行的工具名。
        args: 工具调用参数。
        decision: 人工决策——"allow" / "deny"；pending 时为 None。
        reason: 人工或系统写入的说明。
        status: 会话状态——pending / approved / denied / expired。
        created_at: 创建时的单调时间戳。
        user_response_at: 人工响应时的单调时间戳（未响应为 None）。
    """

    request_id: str
    tool_name: str
    args: dict
    decision: str | None = None
    reason: str | None = None
    status: str = "pending"
    created_at: float = field(default_factory=time.monotonic)
    user_response_at: float | None = None


class HitlManager:
    """HITL 请求总控——内存字典 + 可选 SQLite 持久化。

    Attributes:
        sessions: 当前进程内所有 session 的字典（request_id → HitlSession）。
    """

    def __init__(self, storage: "HitlStorage | None" = None) -> None:
        """初始化管理器。

        Args:
            storage: 可选的 HitlStorage，所有写操作会同步落盘。
        """
        from .storage import HitlStorage

        self._storage: HitlStorage | None = storage
        self.sessions: dict[str, HitlSession] = {}
        self._events: dict[str, asyncio.Event] = {}

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    async def request_approval(self, tool_name: str, args: dict) -> str:
        """发起一次 HITL 请求（pending 状态）。

        Args:
            tool_name: 请求执行的工具名。
            args: 工具参数。

        Returns:
            新生成的 request_id。
        """
        request_id = uuid.uuid4().hex
        session = HitlSession(
            request_id=request_id,
            tool_name=tool_name,
            args=dict(args),
        )
        self.sessions[request_id] = session
        self._events[request_id] = asyncio.Event()

        if self._storage is not None:
            await self._storage.save(session)

        log.info("HITL pending: %s tool=%s", request_id, tool_name)
        return request_id

    async def approve(self, request_id: str, reason: str = "approved") -> HitlSession:
        """批准一次 pending 请求。

        Args:
            request_id: 目标请求。
            reason: 可选说明文字。

        Returns:
            更新后的 HitlSession。

        Raises:
            KeyError: request_id 不存在。
            RuntimeError: 会话已非 pending 状态。
        """
        return await self._resolve(request_id, decision="allow", status="approved", reason=reason)

    async def deny(self, request_id: str, reason: str = "denied") -> HitlSession:
        """拒绝一次 pending 请求。

        Args:
            request_id: 目标请求。
            reason: 可选说明文字。

        Returns:
            更新后的 HitlSession。

        Raises:
            KeyError: request_id 不存在。
            RuntimeError: 会话已非 pending 状态。
        """
        return await self._resolve(request_id, decision="deny", status="denied", reason=reason)

    async def wait_for_decision(
        self, request_id: str, timeout: float = 300.0, poll_interval: float = 0.1
    ) -> HitlSession:
        """等待某次请求产生决策（每 poll_interval 秒轮询一次）。

        用 asyncio.Event 的 wait 做一次性挂起 + 小间隔超时重试，
        避免简单 asyncio.sleep 空等导致事件循环完全阻塞。

        Args:
            request_id: 目标请求。
            timeout: 总等待秒数，超时后 session.status 会被置为 ``expired``。
            poll_interval: Event wait 粒度。

        Returns:
            已决策的 HitlSession（status ∈ {approved, denied, expired}）。

        Raises:
            KeyError: request_id 不存在。
        """
        if request_id not in self.sessions:
            raise KeyError(request_id)

        deadline = time.monotonic() + timeout
        event = self._events.setdefault(request_id, asyncio.Event())

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # 超时，置为 expired
                await self._expire(request_id)
                return self.sessions[request_id]

            # Event.wait 支持 asyncio 感知的定时等待
            try:
                await asyncio.wait_for(event.wait(), timeout=min(poll_interval, remaining))
            except asyncio.TimeoutError:
                continue

            # 被设置了——再确认一次 session 真的不是 pending
            session = self.sessions.get(request_id)
            if session is None or session.status != "pending":
                return session  # type: ignore[return-value]

    def list_pending(self) -> list[HitlSession]:
        """列出所有 pending 状态的 session。

        Returns:
            按 created_at 升序排列。
        """
        pending = [s for s in self.sessions.values() if s.status == "pending"]
        pending.sort(key=lambda s: s.created_at)
        return pending

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _resolve(
        self, request_id: str, *, decision: str, status: str, reason: str
    ) -> HitlSession:
        """把 pending session 推进到终态。"""
        current = self.sessions.get(request_id)
        if current is None:
            raise KeyError(request_id)
        if current.status != "pending":
            raise RuntimeError(
                f"session {request_id} is already in status={current.status}, cannot {status}"
            )

        updated = HitlSession(
            request_id=current.request_id,
            tool_name=current.tool_name,
            args=current.args,
            decision=decision,
            reason=reason,
            status=status,
            created_at=current.created_at,
            user_response_at=time.monotonic(),
        )
        self.sessions[request_id] = updated

        if self._storage is not None:
            await self._storage.save(updated)

        # 唤醒等待方
        event = self._events.pop(request_id, None)
        if event is not None:
            event.set()

        log.info("HITL %s: %s -> %s", status, request_id, decision)
        return updated

    async def _expire(self, request_id: str) -> None:
        """把 pending session 置为 expired。"""
        current = self.sessions.get(request_id)
        if current is None or current.status != "pending":
            return
        updated = HitlSession(
            request_id=current.request_id,
            tool_name=current.tool_name,
            args=current.args,
            decision="deny",
            reason="hitl expired",
            status="expired",
            created_at=current.created_at,
            user_response_at=time.monotonic(),
        )
        self.sessions[request_id] = updated
        if self._storage is not None:
            await self._storage.save(updated)
        event = self._events.pop(request_id, None)
        if event is not None:
            event.set()
        log.warning("HITL expired: %s", request_id)
