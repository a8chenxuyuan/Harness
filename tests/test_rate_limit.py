"""限流测试（W3-PLAT-02）。"""

from __future__ import annotations

import pytest

from harness.platform.api.exceptions import RateLimitError
from harness.platform.service.rate_limit import (
    SlidingWindowLimiter,
    tenant_rate_limit,
)


def test_sliding_window_limits_and_recovers() -> None:
    """窗口内超过上限拒绝，时间滑过后恢复。"""
    now = [0.0]
    limiter = SlidingWindowLimiter(2, window=10, clock=lambda: now[0])

    assert limiter.hit("k")[0] is True
    assert limiter.hit("k")[0] is True
    allowed, retry_after = limiter.hit("k")
    assert allowed is False
    assert retry_after > 0

    now[0] = 11.0
    assert limiter.hit("k")[0] is True


def test_tenant_dependency_raises_retry_after(user_info) -> None:
    """租户维度依赖超限时抛 RateLimitError 并带等待时长。"""
    dep = tenant_rate_limit("unit-test", 1)

    dep(user_info)
    with pytest.raises(RateLimitError) as exc:
        dep(user_info)
    assert exc.value.retry_after >= 1


async def test_login_rate_limit_returns_429(
    client, register_user
) -> None:
    """登录接口按 IP 10 次/分钟，超限返回 429 + Retry-After。"""
    username, password, _ = await register_user()
    body = {"username": username, "password": password}

    for _ in range(10):
        resp = await client.post("/api/v1/auth/login", json=body)
        assert resp.status_code == 200, resp.text

    limited = await client.post("/api/v1/auth/login", json=body)
    assert limited.status_code == 429
    assert limited.headers.get("Retry-After") is not None
    assert limited.json()["code"] == 429
