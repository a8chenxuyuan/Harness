"""Gateway 路由层：按 channel 名把 RawMessage 分发给对应 adapter（Phase 12）。

GatewayRouter 只做三件事：
  1. register(adapter) —— 注册 channel
  2. dispatch(raw, agent_runner) —— 用 agent_runner 拿到回复，再 send 回原 channel
  3. 按 raw.channel 查 adapter

不依赖 FastAPI，可被任何 server 实现复用。
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Callable

from .channel import ChannelAdapter, RawMessage, SendResult

log = logging.getLogger(__name__)

# Agent runner 签名：(RawMessage) -> AsyncIterator[str] | str
AgentRunner = Callable[[RawMessage], Any]


class GatewayRouter:
    """把 channel 消息路由到 Agent 并把回复发回原 channel 的编排器。

    Attributes:
        adapters: 已注册的 adapter 字典（channel_name → adapter）。
    """

    def __init__(self) -> None:
        self.adapters: dict[str, ChannelAdapter] = {}

    # ------------------------------------------------------------------
    # 注册 / 注销
    # ------------------------------------------------------------------

    def register(self, adapter: ChannelAdapter) -> None:
        """注册一个 adapter。

        相同 channel_name 会覆盖旧 adapter（先移除再覆盖，便于热替换）。

        Args:
            adapter: ChannelAdapter 实例。

        Raises:
            ValueError: adapter.channel_name 为空或已存在时（debug 级别 log）。
        """
        name = adapter.channel_name
        if not name:
            raise ValueError("adapter.channel_name must not be empty")

        if name in self.adapters:
            log.info("gateway: adapter %s 已存在，覆盖", name)
        self.adapters[name] = adapter
        log.info("gateway: 注册 adapter %s", name)

    def unregister(self, channel_name: str) -> ChannelAdapter | None:
        """移除并返回指定 channel 的 adapter（调试/热重载用）。

        Args:
            channel_name: 目标 channel。

        Returns:
            被移除的 adapter，没注册过则返回 None。
        """
        return self.adapters.pop(channel_name, None)

    # ------------------------------------------------------------------
    # 核心：dispatch
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        raw: RawMessage,
        agent_runner: AgentRunner,
    ) -> SendResult:
        """把一条 RawMessage 转给 agent_runner，再把回复 send 回原 channel。

        agent_runner 可以返回：
          - 纯字符串（一次性回复）
          - AsyncIterator[str]（流式回复，会自动 join 成一条消息 send 回去）
          - 其他类型（转 str 再 send）

        Args:
            raw: 原始 channel 消息。
            agent_runner: 业务处理函数。

        Returns:
            最终 send 的 SendResult。agent_runner 抛异常也会被捕获，
            返回 ok=False 的 SendResult 而不会中断 router。
        """
        # 1. 找 adapter
        adapter = self.adapters.get(raw.channel)
        if adapter is None:
            log.error("gateway: 未注册的 channel=%s", raw.channel)
            return SendResult(ok=False, error=f"unknown channel: {raw.channel}")

        # 2. 调 agent
        try:
            reply = await agent_runner(raw)
        except Exception as exc:  # noqa: BLE001
            log.exception("gateway: agent_runner 抛异常")
            return await adapter.send(
                f"Agent error: {exc}", raw.channel_user_id
            )

        # 3. reply 可能是 AsyncIterator —— 全部收集
        text = await _collect_reply(reply)

        # 4. send 回去
        return await adapter.send(text, raw.channel_user_id)

    # ------------------------------------------------------------------
    # 便捷：创建所有 adapter 的 receive 任务
    # ------------------------------------------------------------------

    async def run_all(
        self,
        agent_runner: AgentRunner,
        *,
        concurrency: int = 4,
    ) -> None:
        """为每个 adapter.receive 启动 asyncio task，收到消息就 dispatch。

        典型入口：server lifespan 里 ``asyncio.create_task(router.run_all(run))``。
        本方法永不返回，直到进程被取消。

        Args:
            agent_runner: 业务处理函数。
            concurrency: 同一时刻最多并行处理多少条消息。
        """
        import asyncio

        sem = asyncio.Semaphore(concurrency)

        async def _consume(adapter: ChannelAdapter) -> None:
            async for raw in adapter.receive():
                async with sem:
                    asyncio.create_task(self.dispatch(raw, agent_runner))

        tasks = [
            asyncio.create_task(_consume(adapter), name=f"gateway-{name}")
            for name, adapter in self.adapters.items()
        ]
        if tasks:
            await asyncio.gather(*tasks)


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


async def _collect_reply(reply: Any) -> str:
    """把 agent_runner 的返回值统一转成字符串。

    Args:
        reply: 可能是 str / AsyncIterator[str] / 其他。

    Returns:
        拼接后的纯文本。
    """
    import asyncio
    from collections.abc import AsyncIterator as AsyncIteratorABC

    if reply is None:
        return ""
    if isinstance(reply, str):
        return reply

    # AsyncIterator —— 全部收集
    if asyncio.iscoroutine(reply) or hasattr(reply, "__aiter__"):
        try:
            if asyncio.iscoroutine(reply):
                reply = await reply
                # await 之后如果还是 AsyncIterator，继续收集
                if hasattr(reply, "__aiter__"):
                    return await _collect_aiter(reply)
                return str(reply)

            return await _collect_aiter(reply)
        except Exception as exc:  # noqa: BLE001
            log.warning("gateway: 收集流式 reply 时出错: %s", exc)
            return f"(streaming error: {exc})"

    return str(reply)


async def _collect_aiter(aiter: AsyncIterator[str]) -> str:
    """把 AsyncIterator[str] 全部拼接成一个字符串。"""
    parts: list[str] = []
    async for chunk in aiter:
        parts.append(chunk)
    return "".join(parts)
