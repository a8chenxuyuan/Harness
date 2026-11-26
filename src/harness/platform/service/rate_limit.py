"""进程内滑动窗口限流（W3-PLAT-02）。

单实例部署下用内存实现即可挡住突发流量；多实例部署需要换成 Redis
等共享存储，但接口语义（429 + Retry-After）保持不变。

限流维度：
    auth.login       IP          10 次/分钟
    agent.run        租户        30 次/分钟
    agent.run.stream 租户        30 次/分钟
    messages.create  租户        120 次/分钟
    audit.export     租户        5 次/分钟

所有限制值集中在模块底部，便于按环境调整。
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Any, Callable

from fastapi import Depends, Request

from harness.common.observability.metrics import record_rate_limited
from harness.platform.api.deps import get_current_user
from harness.platform.api.exceptions import RateLimitError
from harness.platform.api.vo.auth_vo import UserInfo


class SlidingWindowLimiter:
    """按 key 维护时间窗口内的命中次数。"""

    def __init__(
        self,
        limit: int,
        window: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = max(1, limit)
        self.window = max(0.001, window)
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> tuple[bool, float]:
        """记录一次命中。

        Returns:
            (allowed, retry_after_seconds)；被限流时 retry_after 为建议等待秒数。
        """
        now = self.clock()
        cutoff = now - self.window
        with self._lock:
            queue = self._hits.setdefault(key, deque())
            while queue and queue[0] <= cutoff:
                queue.popleft()
            if len(queue) >= self.limit:
                retry_after = self.window - (now - queue[0])
                return False, max(0.0, retry_after)
            queue.append(now)
            return True, 0.0

    def reset(self) -> None:
        """清空全部计数（测试 / 运维恢复）。"""
        with self._lock:
            self._hits.clear()


_limiters: dict[str, SlidingWindowLimiter] = {}


def get_limiter(name: str, limit: int, window: float = 60.0) -> SlidingWindowLimiter:
    """按名称获取（或创建）全局限流器。"""
    limiter = _limiters.get(name)
    if limiter is None:
        limiter = SlidingWindowLimiter(limit, window)
        _limiters[name] = limiter
    return limiter


def reset_rate_limiters() -> None:
    """重置全部限流器（测试隔离用）。"""
    _limiters.clear()


def _client_ip(request: Request) -> str:
    """取客户端 IP；反向代理下优先 X-Forwarded-For 首段。"""
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


def _enforce(scope: str, limiter: SlidingWindowLimiter, key: str) -> None:
    """命中限流器，超限抛 RateLimitError（429 + Retry-After）。"""
    allowed, retry_after = limiter.hit(key)
    if allowed:
        return
    record_rate_limited(scope)
    raise RateLimitError(
        f"请求过于频繁（{scope}），请 {math.ceil(retry_after)} 秒后重试",
        retry_after=retry_after,
    )


def login_rate_limit(request: Request) -> None:
    """登录接口：按客户端 IP 限制。"""
    _enforce("auth.login", get_limiter("auth.login", 10), _client_ip(request))


def tenant_rate_limit(scope: str, limit: int, window: float = 60.0):
    """构造按租户限流的依赖工厂。"""

    def _dep(user: UserInfo = Depends(get_current_user)) -> None:
        _enforce(scope, get_limiter(scope, limit, window), user.tenant_id)

    return _dep


# 对外暴露的依赖实例（Controller 直接 Depends 使用）
run_rate_limit = tenant_rate_limit("agent.run", 30)
stream_rate_limit = tenant_rate_limit("agent.run.stream", 30)
message_rate_limit = tenant_rate_limit("messages.create", 120)
audit_export_rate_limit = tenant_rate_limit("audit.export", 5)


__all__ = [
    "SlidingWindowLimiter",
    "audit_export_rate_limit",
    "get_limiter",
    "login_rate_limit",
    "message_rate_limit",
    "reset_rate_limiters",
    "run_rate_limit",
    "stream_rate_limit",
    "tenant_rate_limit",
]
