"""平台数据拉取框架（W4.1-CHAN-06）。

ChannelFetcher 基类统一封装四件事，子类只写数据协议：
    1. token 管理     —— 复用渠道 adapter 的 access_token 缓存；
    2. 限频           —— 每次平台请求之间强制间隔，防触发平台限流；
    3. 错误重试       —— 3 次指数退避（0.5s/2s/8s），限频错误退避更久；
    4. 增量同步       —— 游标由基类透传，子类按平台协议解析。

FetchedItem 是拉取结果的统一形状，入库与 EventBus 都消费它。
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

# 重试退避（秒）：普通错误 3 次；平台限频错误单独加时
RETRY_DELAYS: tuple[float, ...] = (0.5, 2.0, 8.0)
RATE_LIMIT_EXTRA: float = 5.0
# 相邻平台请求的最小间隔（秒）
REQUEST_INTERVAL: float = 0.5


@dataclass
class FetchedItem:
    """一条从平台拉到的数据（统一形状）。"""

    external_id: str
    item_type: str  # profile / todo / message
    title: str
    summary: str
    raw: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class FetchError(RuntimeError):
    """平台请求最终失败（重试耗尽）。"""

    def __init__(self, message: str, rate_limited: bool = False) -> None:
        super().__init__(message)
        self.rate_limited = rate_limited


class ChannelFetcher(ABC):
    """数据源基类：一个子类 = 平台 × 一种数据。

    Attributes:
        platform: 渠道标识（wecom / feishu / ...）。
        source:   数据源标识（profile / approval / ...），同时是游标键。
        item_type: 拉取数据的类型标签。
    """

    platform: str = ""
    source: str = ""
    item_type: str = ""

    def __init__(self, adapter: Any) -> None:
        """adapter 提供平台 HTTP 通道与 access_token 缓存。"""
        self.adapter = adapter
        self._last_request_at: float = 0.0

    # --- 供子类使用的平台请求通道（限频 + 重试） -------------------------------

    async def platform_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """带限频与重试的平台 API 调用，返回 JSON。

        Args:
            method: "GET" / "POST"。
            path:   API 路径（相对平台域名）。
            params / json_body: 查询串与请求体。
            base_url: 覆盖平台域名（默认取 adapter.BASE_URL）。

        Raises:
            FetchError: 重试耗尽仍失败。
        """
        import httpx

        url = f"{base_url or getattr(self.adapter, 'BASE_URL', '')}{path}"
        last_exc: Exception | None = None
        for attempt, delay in enumerate((0.0,) + RETRY_DELAYS):
            if delay:
                await asyncio.sleep(delay)
            await self._throttle()
            try:
                async with self._make_client() as client:
                    if method.upper() == "GET":
                        resp = await client.get(url, params=params)
                    else:
                        resp = await client.post(url, params=params, json=json_body or {})
                if resp.status_code in (429,):
                    last_exc = FetchError("rate limited by platform", rate_limited=True)
                    log.warning("fetch[%s/%s]: 平台限流(429)，第 %d 次退避", self.platform, self.source, attempt + 1)
                    continue
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                # 企微风格错误码：errcode 非 0 视为失败（限频码退避更久）
                errcode = data.get("errcode", 0)
                if errcode not in (0, None):
                    rate_limited = errcode in (45009, 45011)
                    last_exc = FetchError(f"platform errcode={errcode} errmsg={data.get('errmsg')}", rate_limited=rate_limited)
                    if rate_limited:
                        await asyncio.sleep(RATE_LIMIT_EXTRA)
                    continue
                return data
            except httpx.HTTPStatusError as exc:
                last_exc = FetchError(f"http {exc.response.status_code}")
            except httpx.HTTPError as exc:
                last_exc = FetchError(f"http error: {exc}")
        raise last_exc or FetchError("unknown fetch failure")

    def _make_client(self) -> Any:
        """构造 http 客户端；adapter 可设 fetch_client_factory 注入 MockTransport（测试用）。"""
        factory = getattr(self.adapter, "fetch_client_factory", None)
        if factory is not None:
            return factory()
        import httpx

        return httpx.AsyncClient(timeout=10.0)

    async def _throttle(self) -> None:
        """相邻请求最小间隔（简单限频）。"""
        import time

        now = time.monotonic()
        wait = REQUEST_INTERVAL - (now - self._last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request_at = time.monotonic()

    # --- 子类实现 -------------------------------------------------------------

    @abstractmethod
    async def fetch(
        self,
        binding: Any,
        cursor: str,
    ) -> tuple[list[FetchedItem], str]:
        """拉取一个绑定用户的数据。

        Args:
            binding: channel_binding 记录（platform_user_id 等字段）。
            cursor:  上次的增量游标（首拉为空串）。

        Returns:
            (本批数据, 新游标)。
        """
        raise NotImplementedError


__all__ = ["ChannelFetcher", "FetchError", "FetchedItem", "RETRY_DELAYS"]
