"""ReAct 循环的图构图 + 简单 runner（Phase 5）。

设计决策：
- LangGraph 0.2 版本可能还在变动，所以本文件用**简单 while runner**
  作为主实现（`run_loop`），保证不依赖 LangGraph 也能跑完整 ReAct 链路。
- LangGraph 包装层 `build_graph()` 只做壳——如果用户装了 langgraph 就返回
  一个编译好的 StateGraph，否则抛 ImportError 提示装依赖。
- 两者共享同一个 AgentState 和 streaming.run_with_stream，避免实现重复。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from harness.core.tool.base import ToolResult
from harness.core.tool.budget import ToolBudget

from .state import AgentState
from .streaming import LoopStreamEvent, run_with_stream

if TYPE_CHECKING:
    from harness.core.context.assembler import ContextAssembler
    from harness.core.model.base import Model
    from harness.core.tool.registry import ToolRegistry


# ---------------------------------------------------------------------------
# 简单 runner：run_loop（主实现）
# ---------------------------------------------------------------------------


async def run_loop(
    state: AgentState,
    model: "Model",
    registry: "ToolRegistry",
    assembler: "ContextAssembler | None" = None,
    budget: ToolBudget | None = None,
) -> AgentState:
    """不依赖 LangGraph 的 while-runner ReAct 循环。

    链路：
    while not stopping and step < max_steps:
        1. （可选）assembler.assemble 做缓存预热
        2. model.stream → 累积 ChatResponse
        3. 有 tool_calls → 串行执行 → 追加 ToolMsg → step += 1 → 回 1
        4. 无 tool_calls → finalize → step += 1 → break

    Args:
        state: 初始化好的 AgentState（至少要有 messages 里的 system + 首条 user）。
        model: 模型实例。
        registry: 工具注册表。
        assembler: 可选的 ContextAssembler；传入则在每轮开头调 assemble 预热缓存。
        budget: 工具预算器；None 则新建一个默认的。

    Returns:
        跑完或终止后的 AgentState。
    """
    budget = budget or ToolBudget()

    while not state.should_stop:
        # 1. 装配（如果给了 assembler）——只为缓存预热，装配结果本身不会改 messages
        if assembler is not None:
            assembler.assemble(
                history=state.messages,
                volatile_context=state.volatile_context,
                session_id=state.session_id,
            )

        # 2. 调 model（用 run_with_stream 消费完流式输出，内部会写入 state）
        async for _event in run_with_stream(state, model, registry, budget):
            # 简单 runner 不 yield 事件，直接消费完。
            # 用户如果要事件流，直接用 run_with_stream 本身。
            pass

        # run_with_stream 内部已经 finalize 了（step += 1, clear_pending），
        # 但如果是 max_steps 退出，需要再检查一次
        if state.hit_max_steps:
            state.mark_stopped("max_steps")
            break

    return state


async def run_loop_with_events(
    state: AgentState,
    model: "Model",
    registry: "ToolRegistry",
    assembler: "ContextAssembler | None" = None,
    budget: ToolBudget | None = None,
) -> "AsyncIterator[LoopStreamEvent]":
    """带事件流的 ReAct 循环（就是 run_with_stream 的别名，提供与 run_loop 对称的 API）。

    Args:
        state: AgentState。
        model: Model。
        registry: ToolRegistry。
        assembler: 可选，仅用于缓存预热（内部会跑 assemble 一次）。
        budget: 可选预算器。

    Yields:
        LoopStreamEvent 流。
    """
    budget = budget or ToolBudget()

    # 先做一次装配（如果有 assembler）
    if assembler is not None:
        assembler.assemble(
            history=state.messages,
            volatile_context=state.volatile_context,
            session_id=state.session_id,
        )

    # 把 run_with_stream 产出的事件原样透传
    async for event in run_with_stream(state, model, registry, budget):
        yield event


# ---------------------------------------------------------------------------
# LangGraph 包装层：build_graph
# ---------------------------------------------------------------------------


def _is_langgraph_available() -> bool:
    try:
        import langgraph  # noqa: F401
        return True
    except ImportError:
        return False


async def _node_assemble(
    state: AgentState,
    assembler: "ContextAssembler",
) -> AgentState:
    """LangGraph assemble 节点：调 ContextAssembler.assemble 做缓存预热。"""
    assembler.assemble(
        history=state.messages,
        volatile_context=state.volatile_context,
        session_id=state.session_id,
    )
    return state


async def _node_model(
    state: AgentState,
    model: "Model",
    registry: "ToolRegistry",
    budget: ToolBudget,
) -> AgentState:
    """LangGraph model 节点：调 run_with_stream 消费 model 输出，写入 state。"""
    # 内部会直接把 assistant msg / tool msg 写进 state
    async for _event in run_with_stream(state, model, registry, budget):
        pass
    return state


async def _node_tools(state: AgentState) -> AgentState:
    """LangGraph tools 节点：run_with_stream 内部已执行工具，这里空占位（兼容旧 graph 结构）。"""
    return state


async def _node_finalize(state: AgentState) -> AgentState:
    """LangGraph finalize 节点：run_with_stream 内部已 finalize，这里只做一次空校验。"""
    if state.hit_max_steps:
        state.mark_stopped("max_steps")
    return state


def build_graph(
    model: "Model",
    registry: "ToolRegistry",
    assembler: "ContextAssembler | None" = None,
    budget: ToolBudget | None = None,
):
    """构造 LangGraph StateGraph（可选依赖，没装 langgraph 会 ImportError）。

    返回一个编译好的 CompiledGraph，可以 .ainvoke(state) 跑完。
    内部节点实际调的是 run_loop 的逻辑——LangGraph 壳只负责边路由。

    Args:
        model: 模型实例。
        registry: 工具注册表。
        assembler: 可选的装配器（assemble 节点用）。
        budget: 可选的预算器。

    Returns:
        langgraph.graph.CompiledGraph 实例。

    Raises:
        ImportError: langgraph 未安装。
    """
    if not _is_langgraph_available():
        raise ImportError(
            "langgraph 未安装。请 pip install langgraph，或使用 run_loop（简单 runner）。"
        )

    from langgraph.graph import END, START, StateGraph

    budget = budget or ToolBudget()

    graph = StateGraph(AgentState)

    # -- 节点 ---------------------------------------------------------------
    if assembler is not None:
        async def assemble_node(state: AgentState) -> AgentState:
            return await _node_assemble(state, assembler)

        graph.add_node("assemble", assemble_node)

    async def model_node(state: AgentState) -> AgentState:
        return await _node_model(state, model, registry, budget)

    graph.add_node("model", model_node)

    # -- 边 -----------------------------------------------------------------
    start_node = "assemble" if assembler is not None else "model"
    graph.add_edge(START, start_node)

    # 条件边：根据 state.pending_tool_calls 和 state.stopping 路由
    def route_after_model(state: AgentState) -> str:
        if state.should_stop:
            return END
        if state.pending_tool_calls:
            # run_with_stream 内部已经执行完工具并 finalize，所以直接回 assemble/model
            return start_node
        return END

    graph.add_conditional_edges("model", route_after_model)

    return graph.compile()
