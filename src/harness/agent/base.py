"""Agent 抽象基类。

:class:`Agent` 是 Harness 对外暴露的「四合一 Agent」统一入口：
ReAct 循环、上下文装配、事件分发、checkpoint 恢复全由子类（主要是
ReActAgent）实现。基类只规定了必须具备的能力：

- ``run(user_input)`` —— 主入口，返回 AgentState
- ``stop()`` / ``steer()`` —— 中途插话（Phase 7 steering）
- ``session_id`` / ``state`` —— 会话可寻址

基类不持有任何具体循环或模型细节，方便未来扩展 Plan-and-Solve、
Tool-use-first 等其他 Agent 形态。
"""

from __future__ import annotations

import abc
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness.context.assembler import ContextAssembler
    from harness.event.bus import EventBus
    from harness.loop.state import AgentState
    from harness.model.base import Model
    from harness.tool.registry import ToolRegistry


class Agent(abc.ABC):
    """所有 Agent 形态的基类。

    Attributes:
        model: 大模型适配器实例。
        tools: 工具注册表；子类会自动把 registry.list_for_llm() 暴露给模型。
        assembler: 可选的 ContextAssembler；传入后每轮开头会调 assemble 预热缓存。
        event_bus: 事件总线；None 则走全局 get_event_bus()。
        max_steps: ReAct 循环硬上限。
        session_id: 会话标识，自动生成或由外部注入。
        volatile_context: 每轮临时注入 ContextAssembler 的键值对。
        taint: 轮次污染标记（Phase 7）。
    """

    def __init__(
        self,
        *,
        model: "Model",
        tools: "ToolRegistry | None" = None,
        assembler: "ContextAssembler | None" = None,
        event_bus: "EventBus | None" = None,
        max_steps: int = 50,
        session_id: str | None = None,
    ) -> None:
        """构造一个 Agent。

        Args:
            model: 必需的大模型实例。
            tools: 可选的工具注册表；None 则空注册表。
            assembler: 可选的 ContextAssembler；传入会自动与 system prompt / tools 对齐。
            event_bus: 可选的事件总线；None 用全局单例。
            max_steps: 循环硬上限。
            session_id: 会话标识；None 自动生成。
        """
        from harness.event.bus import get_event_bus
        from harness.loop.state import AgentState
        from harness.tool.registry import ToolRegistry

        self.model = model
        self.tools = tools or ToolRegistry()
        self.assembler = assembler
        self.event_bus = event_bus or get_event_bus()
        self.max_steps = max_steps
        self.session_id = session_id or f"sess-{uuid.uuid4().hex[:12]}"

        # 可变运行时状态（由 AgentState 承载，但基类先维护几个公共字段）
        self._state: AgentState | None = None
        self._running = False

    # --- 抽象主入口 -----------------------------------------------------------

    @abc.abstractmethod
    async def run(self, user_input: str, **kwargs: Any) -> "AgentState":
        """跑一次 ReAct 循环。

        Args:
            user_input: 用户输入文本。
            **kwargs: 子类可额外注入 volatile_context、system_prompt 等。

        Returns:
            跑完后的 AgentState。
        """
        raise NotImplementedError

    # --- 公共便捷入口 ---------------------------------------------------------

    async def stop(self) -> None:
        """中断正在跑的循环（Phase 7 interrupt）。

        若当前没有 run 中的循环，noop；若有，则调用 :func:`harness.loop.interrupt`
        把 ``stopping`` 设为 True 并在本轮收尾时退出。
        """
        from harness.loop.interrupt import interrupt

        if self._state is not None and self._running:
            interrupt(self._state, reason="agent_stop")

    async def steer(self, message: str) -> "AgentState":
        """中途插话：把一条额外的 user message 注入到当前会话。

        典型场景：Agent 跑了一半，用户说「换一种方式」——steer 会挂起
        当前循环，等下一次 run() 时把这条消息追加进 history。

        Args:
            message: 用户插话文本。

        Returns:
            追加后（可能带恢复）的 AgentState。
        """
        from harness.message.helpers import user_message
        from harness.loop.interrupt import interrupt

        if self._state is None:
            # 还没 run 过，直接初始化 state
            await self.run(message)
            assert self._state is not None
            return self._state

        # 正在跑 → 先中断
        if self._running:
            interrupt(self._state, reason="user_steer")

        self._state.messages.append(user_message(message))
        return self._state

    # --- 只读属性 -------------------------------------------------------------

    @property
    def state(self) -> "AgentState | None":
        """当前 AgentState（未 run 过为 None）。"""
        return self._state

    @property
    def is_running(self) -> bool:
        """当前是否有 run() 在执行。"""
        return self._running
