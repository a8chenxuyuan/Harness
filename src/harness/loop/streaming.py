"""ReAct 循环的流式运行时（Phase 5），末尾追加 Phase 6 并行/重叠扩展。

本文件分两部分：
1. P5 基础：LoopStreamEvent 事件类型 + run_with_stream 串行 runner
2. P6 扩展（在文件末尾，用注释分区）：schedule_overlapped_tools / execute_with_overlap

设计原则：Phase 6 扩展**不覆盖** Phase 5 代码，而是在末尾追加新函数和
新事件类型常量。这样用户可以单独 import P5 的 run_with_stream，
也可以 import Phase 6 的 execute_with_overlap，两者互不干扰。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator

from harness.message.content_block import TextBlock, ToolUseBlock
from harness.message.helpers import assistant_message, tool_result_message
from harness.model.types import (
    ChatChunk,
    ChatResponse,
    GenerateOptions,
    ToolCall,
    ToolCallDelta,
)
from harness.tool.base import ToolResult
from harness.tool.budget import ToolBudget

if TYPE_CHECKING:
    from harness.model.base import Model
    from harness.tool.registry import ToolRegistry

from .state import AgentState

# ---------------------------------------------------------------------------
# 事件类型常量（P5）
# ---------------------------------------------------------------------------

EVENT_TEXT_DELTA = "text_delta"
EVENT_TOOL_CALL_DELTA = "tool_call_delta"
EVENT_FINISH = "finish"
EVENT_TOOL_START = "tool_start"
EVENT_TOOL_END = "tool_end"
EVENT_ASSEMBLED = "assembled"
EVENT_ERROR = "error"

# ---------------------------------------------------------------------------
# 事件类型常量（P6 追加）
# ---------------------------------------------------------------------------

EVENT_TOOL_GROUP_START = "tool_group_start"
EVENT_TOOL_GROUP_END = "tool_group_end"
EVENT_OVERLAP_SCHEDULED = "overlap_scheduled"
EVENT_TOOL_BATCH_START = "tool_batch_start"
EVENT_TOOL_BATCH_END = "tool_batch_end"


@dataclass(frozen=True)
class LoopStreamEvent:
    """流式运行时的统一事件包。

    frozen dataclass 让事件可以安全地跨 asyncio 任务传递，
    也方便在 EventBus 里原样 publish。

    Attributes:
        event_type: 事件类型常量（见上面的 EVENT_*）。
        payload: 附加数据字典，结构随事件类型变化。
    """

    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 内部辅助：累积 ChatChunk → ChatResponse + 完整 ToolCall 列表
# ---------------------------------------------------------------------------


def _new_tool_call_fragments() -> dict[int, list[str]]:
    """初始化 tool_call delta 累积器。"""
    return {}


def _new_tool_call_meta() -> dict[int, ToolCall]:
    """初始化 tool_call 元信息累积器（id / name 按 index）。"""
    return {}


async def _execute_tool_safely(
    registry: "ToolRegistry",
    budget: ToolBudget,
    call: ToolCall,
) -> ToolResult:
    """执行单个工具，处理去重、异常捕获和预算截断。

    Args:
        registry: 工具注册表。
        budget: 预算器（去重 + 截断）。
        call: 要执行的 tool call。

    Returns:
        ToolResult 实例；即使抛异常也返回 ok=False 的 ToolResult。
    """
    # 1. 预算层去重检查
    cached = budget.check_dedup(call.name, call.arguments)
    if cached is not None:
        return cached

    # 2. 查工具
    try:
        tool = registry.get(call.name)
    except KeyError as exc:
        return ToolResult(ok=False, output="", error=f"未知工具: {call.name} ({exc})")

    # 3. 执行（计时 + 捕获异常）
    start = time.monotonic()
    try:
        result = await tool.execute(**call.arguments)
    except Exception as exc:  # noqa: BLE001 - 工具抛什么都要吞掉
        elapsed_ms = (time.monotonic() - start) * 1000
        budget.record_dedup(call.name, call.arguments, ToolResult(
            ok=False, output="", error=str(exc), execution_time_ms=elapsed_ms
        ))
        return ToolResult(ok=False, output="", error=str(exc), execution_time_ms=elapsed_ms)

    elapsed_ms = (time.monotonic() - start) * 1000
    # 4. 预算截断 + 记 dedup
    truncated = budget.wrap_result(result)
    budget.record_dedup(call.name, call.arguments, truncated)
    # 给 result 补上真实耗时（如果原 result 没填）
    if truncated.execution_time_ms == 0.0:
        truncated = truncated.model_copy(update={"execution_time_ms": elapsed_ms})
    return truncated


async def _execute_tool_list_serial(
    state: AgentState,
    registry: "ToolRegistry",
    budget: ToolBudget,
    calls: list[ToolCall],
) -> list[tuple[ToolCall, ToolResult]]:
    """串行执行一批 tool_call，每发一条就产 ToolMsg。

    Args:
        state: AgentState，结果会追加到 state.tool_results 和 state.messages。
        registry: 工具注册表。
        budget: 预算器。
        calls: 要执行的工具调用列表。

    Returns:
        (ToolCall, ToolResult) 对应列表。
    """
    results: list[tuple[ToolCall, ToolResult]] = []
    for call in calls:
        result = await _execute_tool_safely(registry, budget, call)
        results.append((call, result))

        # 写入 state
        tool_msg = tool_result_message(
            tool_use_id=call.id,
            tool_name=call.name,
            output=result.output or (result.error or ""),
            is_error=not result.ok,
        )
        state.append_tool_result(tool_msg)
    return results


# ---------------------------------------------------------------------------
# P5 主入口：run_with_stream
# ---------------------------------------------------------------------------


async def run_with_stream(
    state: AgentState,
    model: "Model",
    registry: "ToolRegistry",
    budget: ToolBudget,
) -> AsyncIterator[LoopStreamEvent]:
    """P5 基础：串行版流式 ReAct runner。

    每轮：
    1. model.stream → 发 text_delta / tool_call_delta
    2. finish 时累积 ChatResponse
    3. 有 tool_calls → 串行 execute → 追加 ToolMsg → 继续下一轮
    4. 无 tool_calls 或 stopping=True → 发 finish → 返回

    Args:
        state: AgentState 实例。
        model: 已配置好的模型。
        registry: 工具注册表。
        budget: 工具预算器。

    Yields:
        LoopStreamEvent 实例。
    """
    while not state.should_stop:
        # 1. 调 model.stream（默认 GenerateOptions，stream=True）
        opts = GenerateOptions()
        text_parts: list[str] = []
        tool_json_fragments = _new_tool_call_fragments()
        tool_call_meta = _new_tool_call_meta()
        last_finish_reason = "stop"

        yield LoopStreamEvent(
            event_type=EVENT_ASSEMBLED,
            payload={"step": state.step, "session_id": state.session_id},
        )

        try:
            async for chunk in model.stream(state.messages, registry.list_for_llm(), opts):
                # 文本增量
                if chunk.delta:
                    text_parts.append(chunk.delta)
                    yield LoopStreamEvent(
                        event_type=EVENT_TEXT_DELTA,
                        payload={"delta": chunk.delta, "step": state.step},
                    )

                # tool_call 增量累积
                for delta in chunk.tool_calls_delta:
                    meta = tool_call_meta.setdefault(
                        delta.index, ToolCall(id="", name="", arguments={})
                    )
                    if delta.id is not None:
                        meta.id = delta.id
                    if delta.name is not None:
                        meta.name = delta.name
                    if delta.arguments_delta:
                        tool_json_fragments.setdefault(delta.index, []).append(
                            delta.arguments_delta
                        )
                    yield LoopStreamEvent(
                        event_type=EVENT_TOOL_CALL_DELTA,
                        payload={
                            "index": delta.index,
                            "id": delta.id,
                            "name": delta.name,
                            "arguments_delta": delta.arguments_delta,
                        },
                    )

                if chunk.finish_reason is not None:
                    last_finish_reason = chunk.finish_reason
        except Exception as exc:  # noqa: BLE001
            yield LoopStreamEvent(
                event_type=EVENT_ERROR,
                payload={"error": str(exc), "step": state.step},
            )
            state.mark_stopped(f"model_error: {exc}")
            return

        # 2. 拼完整 ChatResponse
        tool_calls: list[ToolCall] = []
        for idx, meta in tool_call_meta.items():
            raw_json = "".join(tool_json_fragments.get(idx, []))
            try:
                arguments = json.loads(raw_json) if raw_json else {}
            except json.JSONDecodeError:
                arguments = {"__raw__": raw_json}
            tool_calls.append(ToolCall(id=meta.id, name=meta.name, arguments=arguments))

        full_text = "".join(text_parts)

        # 3. 把 assistant 消息写入 state
        if tool_calls or full_text:
            tool_uses = [
                ToolUseBlock(id=tc.id, name=tc.name, input=tc.arguments) for tc in tool_calls
            ]
            assistant_msg = assistant_message(text=full_text or None, tool_uses=tool_uses or None)
            state.messages.append(assistant_msg)
            state.last_response_text = full_text

        state.pending_tool_calls = tool_calls

        # 4. 发 finish 事件
        yield LoopStreamEvent(
            event_type=EVENT_FINISH,
            payload={
                "text": full_text,
                "tool_calls": [tc.name for tc in tool_calls],
                "finish_reason": last_finish_reason,
                "step": state.step,
            },
        )

        # 5. 如果有 tool_calls → 串行执行
        if tool_calls:
            yield LoopStreamEvent(
                event_type=EVENT_TOOL_START,
                payload={"tool_count": len(tool_calls), "step": state.step},
            )
            await _execute_tool_list_serial(state, registry, budget, tool_calls)
            yield LoopStreamEvent(
                event_type=EVENT_TOOL_END,
                payload={"tool_count": len(tool_calls), "step": state.step},
            )
        else:
            # 助手没发 tool_call → 正常结束
            state.step += 1
            return

        # 6. finalize：清理 pending + step += 1
        state.clear_pending()
        state.step += 1

    # 循环退出（stopping 或 max_steps）——再发一次 finish 让下游知道
    yield LoopStreamEvent(
        event_type=EVENT_FINISH,
        payload={
            "stop_reason": state.stop_reason or "max_steps",
            "step": state.step,
        },
    )


# ===================================================================
# ===== Phase 6: Overlap & Parallel =====
# ===================================================================
# 下面的代码只在 Phase 6 依赖就绪后被使用；Phase 5 的 run_with_stream
# 完全不引用下面的符号，保持向后兼容。


# ---------------------------------------------------------------------------
# schedule_overlapped_tools：边等模型 finish 边调度已齐的 tool_call
# ---------------------------------------------------------------------------


async def schedule_overlapped_tools(
    chunk_stream: AsyncIterator[ChatChunk],
    state: AgentState,
    registry: "ToolRegistry",
    budget: ToolBudget,
    concurrency: int = 4,
) -> AsyncIterator[LoopStreamEvent]:
    """Phase 6 重叠执行：不等模型整条回复 finish，一拿到完整 tool_call 就调度。

    实现思路：
    - 维护一个队列 queue.Queue
    - 启动一个 consumer task，从队列取完整 tool_call 并并发执行
    - 主迭代器消费 model.stream；每当某个 tool_call 的 index 累积完整
      （id/name 都有了，arguments_delta 最后一块也到了），就 push 进队列
    - chunk_stream finish 后往队列放 sentinel，consumer 任务自然结束
    - 工具结果同步写回 state.messages / state.tool_results

    Args:
        chunk_stream: model.stream 返回的 AsyncIterator[ChatChunk]。
        state: AgentState。
        registry: 工具注册表。
        budget: 工具预算器。
        concurrency: 最大并发数，默认 4。

    Yields:
        LoopStreamEvent，包括 tool_start/tool_end/tool_group_start/tool_group_end/overlap_scheduled。
    """
    from .admission import plan_batch

    # 队列元素：tool call tuple (index, ToolCall) 或 None（sentinel）
    queue: asyncio.Queue[tuple[int, ToolCall] | None] = asyncio.Queue()
    sem = asyncio.Semaphore(concurrency)

    # tool_call 累积状态（同 P5 主循环）
    tool_json_fragments = _new_tool_call_fragments()
    tool_call_meta = _new_tool_call_meta()
    # 标记某个 index 是否已经 "完整并推入队列"
    enqueued: set[int] = set()
    # 标记某个 index 的 arguments 是否刚到尾部（简化：我们在 finish_reason 到来时统一 flush）
    # 更激进的策略是：每个 tool_call 在 arguments_delta 不再产生时就 flush。

    # consumer：从队列取 call 并发执行
    async def _consumer() -> None:
        tasks: list[asyncio.Task[tuple[ToolCall, ToolResult]]] = []
        while True:
            item = await queue.get()
            if item is None:
                # finish 后把所有未完成的任务等完
                if tasks:
                    results = await asyncio.gather(*tasks)
                    for call, result in results:
                        tool_msg = tool_result_message(
                            tool_use_id=call.id,
                            tool_name=call.name,
                            output=result.output or (result.error or ""),
                            is_error=not result.ok,
                        )
                        state.append_tool_result(tool_msg)
                break

            idx, call = item
            async with sem:
                tasks.append(asyncio.create_task(_execute_tool_safely(registry, budget, call)))
            # 每推一个新 call 就发 overlap_scheduled 事件
            # （consumer 本身不 yield event，所以这里需要一个回调通道——
            #  简化实现：consumer 直接写 state，主循环负责发事件）

    consumer_task = asyncio.create_task(_consumer())

    async for chunk in chunk_stream:
        # 照常累积 text（但这里不发 text_delta，text_delta 由上层 model streaming 负责）
        for delta in chunk.tool_calls_delta:
            meta = tool_call_meta.setdefault(
                delta.index, ToolCall(id="", name="", arguments={})
            )
            if delta.id is not None:
                meta.id = delta.id
            if delta.name is not None:
                meta.name = delta.name
            if delta.arguments_delta:
                tool_json_fragments.setdefault(delta.index, []).append(
                    delta.arguments_delta
                )

            # 一旦 id + name 都齐全，且 arguments_delta 最后一块也到了——
            # 简化：先看 finish_reason，或者 id 和 name 都非空就推
            if (
                delta.index not in enqueued
                and meta.id
                and meta.name
                and chunk.finish_reason is not None
            ):
                raw_json = "".join(tool_json_fragments.get(delta.index, []))
                try:
                    arguments = json.loads(raw_json) if raw_json else {}
                except json.JSONDecodeError:
                    arguments = {"__raw__": raw_json}
                full_call = ToolCall(id=meta.id, name=meta.name, arguments=arguments)
                enqueued.add(delta.index)
                await queue.put((delta.index, full_call))
                yield LoopStreamEvent(
                    event_type=EVENT_OVERLAP_SCHEDULED,
                    payload={"tool_name": meta.name, "step": state.step},
                )

    # chunk_stream 结束，放 sentinel
    await queue.put(None)
    await consumer_task


# ---------------------------------------------------------------------------
# ToolExecutor：Phase 6 的执行器，封装 admission + gather
# ---------------------------------------------------------------------------


class ToolExecutor:
    """Phase 6 并行执行器。

    内部用 admission.plan_batch 把一批 calls 切成串行批，
    批内 asyncio.gather、批间串行。

    Attributes:
        registry: 工具注册表。
        budget: 工具预算器。
        concurrency: 最大并发 gather 任务数。
    """

    def __init__(
        self,
        registry: "ToolRegistry",
        budget: ToolBudget | None = None,
        concurrency: int = 4,
    ) -> None:
        self.registry = registry
        self.budget = budget or ToolBudget()
        self.concurrency = concurrency

    async def execute_batch(
        self,
        calls: list[tuple[str, dict[str, Any]]],
    ) -> list[ToolResult]:
        """执行一批 (tool_name, args)，按 admission 结果分批。

        Args:
            calls: 待执行的工具调用列表。

        Returns:
            ToolResult 列表，顺序与输入 calls 对应。
        """
        from .admission import plan_batch

        batches = plan_batch(calls, self.registry)
        sem = asyncio.Semaphore(self.concurrency)
        all_results: list[ToolResult] = []

        for batch in batches:
            # 同一批 gather
            tasks: list[asyncio.Task[ToolResult]] = []
            for name, args in batch:
                async with sem:
                    task = asyncio.create_task(
                        _execute_tool_safely(
                            self.registry,
                            self.budget,
                            ToolCall(id="", name=name, arguments=args),
                        )
                    )
                    tasks.append(task)
            batch_results = await asyncio.gather(*tasks)
            all_results.extend(batch_results)

        return all_results


# ---------------------------------------------------------------------------
# execute_with_overlap：Phase 6 主入口
# ---------------------------------------------------------------------------


async def execute_with_overlap(
    state: AgentState,
    model: "Model",
    registry: "ToolRegistry",
    budget: ToolBudget,
    concurrency: int = 4,
) -> AsyncIterator[LoopStreamEvent]:
    """Phase 6 主入口：边模型流式边并发执行工具，批内 gather 批间串行。

    与 run_with_stream 的核心区别：
    - model.stream 一结束（finish_reason 到来）就立刻把所有完整的 tool_call
      丢给 ToolExecutor 并发执行
    - 只读工具 gather，写工具按 admission 结果串行

    Args:
        state: AgentState。
        model: 模型。
        registry: 工具注册表。
        budget: 工具预算器。
        concurrency: 最大并发。

    Yields:
        LoopStreamEvent 流。
    """
    from .admission import plan_batch

    executor = ToolExecutor(registry, budget, concurrency)
    sem = asyncio.Semaphore(concurrency)

    while not state.should_stop:
        opts = GenerateOptions()
        text_parts: list[str] = []
        tool_json_fragments = _new_tool_call_fragments()
        tool_call_meta = _new_tool_call_meta()
        last_finish_reason = "stop"

        yield LoopStreamEvent(
            event_type=EVENT_ASSEMBLED,
            payload={"step": state.step},
        )

        # 1. 流式消费
        async for chunk in model.stream(state.messages, registry.list_for_llm(), opts):
            if chunk.delta:
                text_parts.append(chunk.delta)
                yield LoopStreamEvent(
                    event_type=EVENT_TEXT_DELTA,
                    payload={"delta": chunk.delta, "step": state.step},
                )

            for delta in chunk.tool_calls_delta:
                meta = tool_call_meta.setdefault(
                    delta.index, ToolCall(id="", name="", arguments={})
                )
                if delta.id is not None:
                    meta.id = delta.id
                if delta.name is not None:
                    meta.name = delta.name
                if delta.arguments_delta:
                    tool_json_fragments.setdefault(delta.index, []).append(
                        delta.arguments_delta
                    )
                yield LoopStreamEvent(
                    event_type=EVENT_TOOL_CALL_DELTA,
                    payload={
                        "index": delta.index,
                        "id": delta.id,
                        "name": delta.name,
                        "arguments_delta": delta.arguments_delta,
                    },
                )

            if chunk.finish_reason is not None:
                last_finish_reason = chunk.finish_reason

        # 2. 拼完整 tool_calls
        tool_calls: list[ToolCall] = []
        for idx, meta in tool_call_meta.items():
            raw_json = "".join(tool_json_fragments.get(idx, []))
            try:
                arguments = json.loads(raw_json) if raw_json else {}
            except json.JSONDecodeError:
                arguments = {"__raw__": raw_json}
            tool_calls.append(ToolCall(id=meta.id, name=meta.name, arguments=arguments))
        tool_calls.sort(key=lambda tc: tc.id)  # 稳定顺序

        full_text = "".join(text_parts)

        # 3. assistant 消息入库
        if tool_calls or full_text:
            tool_uses = [
                ToolUseBlock(id=tc.id, name=tc.name, input=tc.arguments) for tc in tool_calls
            ]
            assistant_msg = assistant_message(text=full_text or None, tool_uses=tool_uses or None)
            state.messages.append(assistant_msg)
            state.last_response_text = full_text

        state.pending_tool_calls = tool_calls

        yield LoopStreamEvent(
            event_type=EVENT_FINISH,
            payload={
                "text": full_text,
                "tool_calls": [tc.name for tc in tool_calls],
                "finish_reason": last_finish_reason,
                "step": state.step,
            },
        )

        # 4. 并发执行工具
        if tool_calls:
            # 转成 admission 需要的 (name, args) tuple
            call_tuples = [(tc.name, tc.arguments) for tc in tool_calls]
            batches = plan_batch(call_tuples, registry)

            yield LoopStreamEvent(
                event_type=EVENT_TOOL_BATCH_START,
                payload={"total": len(tool_calls), "batches": len(batches), "step": state.step},
            )

            # 执行：批内 gather + Semaphore
            call_map = {tc.name: tc for tc in tool_calls}
            for batch_idx, batch in enumerate(batches):
                yield LoopStreamEvent(
                    event_type=EVENT_TOOL_GROUP_START,
                    payload={
                        "batch_index": batch_idx,
                        "tool_names": [n for n, _ in batch],
                        "step": state.step,
                    },
                )

                tasks: list[asyncio.Task[tuple[str, dict[str, Any], ToolResult]]] = []
                for name, args in batch:
                    async with sem:
                        task = asyncio.create_task(
                            _execute_tool_safely(
                                registry,
                                budget,
                                ToolCall(id=call_map[name].id, name=name, arguments=args),
                            )
                        )
                        tasks.append(task)

                # gather 并把 ToolMsg 入库
                results = await asyncio.gather(*tasks)
                for call, result in results:
                    tool_msg = tool_result_message(
                        tool_use_id=call_map[call.name].id,
                        tool_name=call.name,
                        output=result.output or (result.error or ""),
                        is_error=not result.ok,
                    )
                    state.append_tool_result(tool_msg)

                yield LoopStreamEvent(
                    event_type=EVENT_TOOL_GROUP_END,
                    payload={
                        "batch_index": batch_idx,
                        "tool_count": len(batch),
                        "step": state.step,
                    },
                )

            yield LoopStreamEvent(
                event_type=EVENT_TOOL_BATCH_END,
                payload={"total": len(tool_calls), "step": state.step},
            )
        else:
            state.step += 1
            return

        # 5. finalize
        state.clear_pending()
        state.step += 1

    yield LoopStreamEvent(
        event_type=EVENT_FINISH,
        payload={
            "stop_reason": state.stop_reason or "max_steps",
            "step": state.step,
        },
    )
