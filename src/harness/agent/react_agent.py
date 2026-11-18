"""ReActAgent —— Harness 对外的主 Agent 实现。

职责：把 loop / context / event / session / observability 各子包组装成
一个好用的 Agent 入口。run() 过程：

1. 初始化 / 加载 AgentState（session_id 自动生成；可选从 checkpoint 恢复）
2. state.messages += 新的 user message
3. 调 loop.react_graph.run_loop（或流式 run_with_stream）跑完 ReAct 循环
4. 把 LoopStreamEvent 转发到 EventBus（如果订阅者存在）
5. 记录 observability 指标（TTFT / loop_iterations）
6. 保存 checkpoint（如果注入了 session.CheckpointManager）

基类 Agent 已经提供了 stop() / steer() / state 属性，这里直接复用。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, AsyncIterator

from .base import Agent

if TYPE_CHECKING:
    from harness.context.assembler import ContextAssembler
    from harness.event.bus import EventBus
    from harness.loop.state import AgentState
    from harness.model.base import Model
    from harness.session.checkpoint import CheckpointManager
    from harness.tool.registry import ToolRegistry

log = logging.getLogger(__name__)


class ReActAgent(Agent):
    """ReAct 循环驱动的 Agent。

    构造时的依赖图（全部可延迟构造）：

    - model —— 必需
    - tools —— 可选；空注册表也能跑（只是不会发 tool_call）
    - assembler —— 可选；传入则每轮开头调 assemble 预热缓存
    - event_bus —— 可选；默认全局单例
    - checkpoint —— 可选；传入则 run() 结束时自动保存、下次 run() 可恢复

    Attributes:
        system_prompt: 系统提示正文（可选，默认一个通用 ReAct 提示）。
        checkpoint: 可选的 CheckpointManager；负责持久化 AgentState。
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
        system_prompt: str | None = None,
        checkpoint: "CheckpointManager | None" = None,
    ) -> None:
        super().__init__(
            model=model,
            tools=tools,
            assembler=assembler,
            event_bus=event_bus,
            max_steps=max_steps,
            session_id=session_id,
        )
        self.system_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT
        self.checkpoint = checkpoint

    # ------------------------------------------------------------------
    # run 主入口
    # ------------------------------------------------------------------

    async def run(self, user_input: str, **kwargs: Any) -> "AgentState":
        """跑一次 ReAct 循环，返回最终的 AgentState。

        Args:
            user_input: 用户输入文本。
            **kwargs: 预留；当前支持 ``volatile_context``（会注入
                AgentState.volatile_context，assembler 每轮会带进去）。

        Returns:
            跑完或终止后的 AgentState。
        """
        # 1. 构造 / 加载 state
        state = await self._ensure_state()

        # 2. 追加 user message
        from harness.message.helpers import user_message

        state.messages.append(user_message(user_input))

        # 3. 注入 volatile_context（如果有）
        if "volatile_context" in kwargs:
            state.volatile_context.update(kwargs["volatile_context"])

        # 4. 跑 loop
        try:
            self._running = True
            result = await self._run_loop(state)
        finally:
            self._running = False

        # 5. 持久化 checkpoint
        await self._maybe_save_checkpoint(result)

        self._state = result
        return result

    async def run_stream(self, user_input: str, **kwargs: Any) -> AsyncIterator[Any]:
        """与 run() 等价，但以 LoopStreamEvent 流的形式返回。

        每轮循环会产出 EVENT_TEXT_DELTA / EVENT_TOOL_CALL_DELTA / EVENT_FINISH 等事件。

        Args:
            user_input: 用户输入文本。
            **kwargs: 同 run()。

        Yields:
            每个 LoopStreamEvent 实例。
        """
        from harness.loop.streaming import LoopStreamEvent, run_with_stream
        from harness.message.helpers import user_message
        from harness.loop.state import AgentState
        from harness.tool.budget import ToolBudget

        state = await self._ensure_state()
        state.messages.append(user_message(user_input))

        if "volatile_context" in kwargs:
            state.volatile_context.update(kwargs["volatile_context"])

        budget = ToolBudget()
        try:
            self._running = True
            async for event in run_with_stream(state, self.model, self.tools, budget):
                # 转发到 EventBus（fire-and-forget）
                await self._publish_loop_event(event)
                yield event
        finally:
            self._running = False
            self._state = state
            await self._maybe_save_checkpoint(state)

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    async def _ensure_state(self) -> "AgentState":
        """第一次 run() 时构造 state，否则复用已有 state。

        若 checkpoint 可用，先尝试从 checkpoint 恢复 session_id 对应的 state。
        """
        from harness.loop.state import AgentState
        from harness.message.helpers import system_message

        if self._state is not None:
            return self._state

        # 尝试 checkpoint 恢复
        if self.checkpoint is not None:
            loaded = self._try_load_checkpoint()
            if loaded is not None:
                return loaded

        # 全新会话
        state = AgentState(session_id=self.session_id, max_steps=self.max_steps)
        state.messages.append(system_message(self.system_prompt))

        # 如果有 assembler，同步它
        if self.assembler is not None:
            self._align_assembler(state)

        return state

    def _try_load_checkpoint(self) -> "AgentState | None":
        """非侵入式尝试从 checkpoint 恢复。失败则静默返回 None。"""
        if self.checkpoint is None:
            return None
        try:
            return self.checkpoint.load(self.session_id)
        except Exception:  # noqa: BLE001
            log.debug("checkpoint 加载失败，将新建 state", exc_info=True)
            return None

    def _align_assembler(self, state: "AgentState") -> None:
        """让 assembler 与当前 state 对齐（主要是 session_id）。"""
        # assembler 本身是无状态的，每次 assemble 带 session_id 即可
        state.session_id = self.session_id

    async def _run_loop(self, state: "AgentState") -> "AgentState":
        """实际跑 ReAct 循环；这里选 run_loop（简单 runner），避免 LangGraph 硬依赖。"""
        from harness.observability.metrics import record_loop_iteration, record_ttft
        from harness.loop.react_graph import run_loop
        import time

        start = time.monotonic()
        result = await run_loop(
            state,
            self.model,
            self.tools,
            assembler=self.assembler,
        )
        elapsed = time.monotonic() - start

        # 埋点
        record_loop_iteration(session_id=self.session_id)
        record_ttft(elapsed, session_id=self.session_id)

        return result

    async def _publish_loop_event(self, event: Any) -> None:
        """把 LoopStreamEvent 原样转发到 EventBus。

        EventBus.publish 是 async 且 handler 失败不冒泡，这里包一层 try。
        """
        try:
            # harness.event.Event 需要 EventType，但 LoopStreamEvent 只有 event_type 字符串，
            # 所以这里用一个轻量包装
            from harness.event.types import Event, EventType

            etype = EventType(event.event_type)
            bus_event = Event(type=etype, payload=event.payload)
            await self.event_bus.publish(bus_event)
        except Exception:  # noqa: BLE001
            # 可能 EventType 里没注册这个 event_type，或者 handler 异常；静默忽略
            pass

    async def _maybe_save_checkpoint(self, state: "AgentState") -> None:
        """run() 结束后如果注入了 CheckpointManager，就保存一份。"""
        if self.checkpoint is None:
            return
        try:
            self.checkpoint.save(state)
        except Exception:  # noqa: BLE001
            log.debug("checkpoint 保存失败（非阻塞）", exc_info=True)


# ---------------------------------------------------------------------------
# 默认系统提示
# ---------------------------------------------------------------------------

_DEFAULT_SYSTEM_PROMPT = (
    "你是 Harness，一个能力全面的 AI 助手。你可以使用提供的工具来帮助用户。\n"
    "每次回答时先思考（thought），如果需要用工具就调用工具；如果不需要，直接给出最终答复。\n"
    "请用简洁中文回答。"
)
