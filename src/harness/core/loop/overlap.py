"""Phase 6：工具重叠调度与并发执行（从 streaming.py 拆出）。

    - schedule_overlapped_tools：边等模型 finish 边调度完整 tool_call
    - ToolExecutor：admission 分批 + 批内 gather / 批间串行
    - execute_with_overlap：Phase 6 主入口

事件常量与共享辅助统一复用 ``.streaming``。
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, AsyncIterator

from harness.common.message.helpers import tool_result_message
from harness.core.model.types import (
    ChatChunk,
    GenerateOptions,
    ToolCall,
    Usage,
    merge_usage,
)
from harness.core.tool.base import ToolResult
from harness.core.tool.budget import ToolBudget

from .state import AgentState
from .streaming import (
    EVENT_ASSEMBLED,
    EVENT_FINISH,
    EVENT_OVERLAP_SCHEDULED,
    EVENT_TEXT_DELTA,
    EVENT_TOOL_BATCH_END,
    EVENT_TOOL_BATCH_START,
    EVENT_TOOL_CALL_DELTA,
    EVENT_TOOL_GROUP_END,
    EVENT_TOOL_GROUP_START,
    LoopStreamEvent,
    _append_assistant,
    _assemble_tool_calls,
    _execute_tool_safely,
    _new_tool_call_fragments,
    _new_tool_call_meta,
)

if TYPE_CHECKING:
    from harness.core.model.base import Model
    from harness.core.tool.registry import ToolRegistry


async def schedule_overlapped_tools(
    chunk_stream: AsyncIterator[ChatChunk],
    state: AgentState,
    registry: "ToolRegistry",
    budget: ToolBudget,
    concurrency: int = 4,
) -> AsyncIterator[LoopStreamEvent]:
    """边消费模型流边调度完整 tool_call（不阻塞等待整条回复）。

    完整判定：id + name 齐全且 chunk 带 finish_reason；
    工具结果由 consumer 协程写回 state，流结束后统一 gather。
    """
    queue: asyncio.Queue[tuple[int, ToolCall] | None] = asyncio.Queue()
    sem = asyncio.Semaphore(concurrency)
    tool_json_fragments = _new_tool_call_fragments()
    tool_call_meta = _new_tool_call_meta()
    enqueued: set[int] = set()

    async def _consumer() -> None:
        tasks: list[asyncio.Task[tuple[ToolCall, ToolResult]]] = []
        while True:
            item = await queue.get()
            if item is None:
                if tasks:
                    for call, result in await asyncio.gather(*tasks):
                        state.append_tool_result(
                            tool_result_message(
                                tool_use_id=call.id,
                                tool_name=call.name,
                                output=result.output or (result.error or ""),
                                is_error=not result.ok,
                            )
                        )
                break
            _, call = item
            async with sem:
                tasks.append(
                    asyncio.create_task(_execute_tool_safely(registry, budget, call))
                )

    consumer_task = asyncio.create_task(_consumer())

    async for chunk in chunk_stream:
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
                enqueued.add(delta.index)
                await queue.put(
                    (delta.index, ToolCall(id=meta.id, name=meta.name, arguments=arguments))
                )
                yield LoopStreamEvent(
                    event_type=EVENT_OVERLAP_SCHEDULED,
                    payload={"tool_name": meta.name, "step": state.step},
                )

    await queue.put(None)
    await consumer_task


class ToolExecutor:
    """Phase 6 并行执行器：内部用 admission.plan_batch 切批。"""

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
        """执行一批 (tool_name, args)：批内 gather、批间串行。"""
        from .admission import plan_batch

        batches = plan_batch(calls, self.registry)
        sem = asyncio.Semaphore(self.concurrency)
        all_results: list[ToolResult] = []

        for batch in batches:
            tasks: list[asyncio.Task[ToolResult]] = []
            for name, args in batch:
                async with sem:
                    tasks.append(
                        asyncio.create_task(
                            _execute_tool_safely(
                                self.registry,
                                self.budget,
                                ToolCall(id="", name=name, arguments=args),
                            )
                        )
                    )
            all_results.extend(await asyncio.gather(*tasks))

        return all_results


async def execute_with_overlap(
    state: AgentState,
    model: "Model",
    registry: "ToolRegistry",
    budget: ToolBudget,
    concurrency: int = 4,
) -> AsyncIterator[LoopStreamEvent]:
    """Phase 6 主入口：边流式边执行工具，批内 gather 批间串行。"""
    from .admission import plan_batch

    sem = asyncio.Semaphore(concurrency)

    while not state.should_stop:
        opts = GenerateOptions()
        text_parts: list[str] = []
        tool_json_fragments = _new_tool_call_fragments()
        tool_call_meta = _new_tool_call_meta()
        last_finish_reason = "stop"
        round_usage = Usage()

        yield LoopStreamEvent(event_type=EVENT_ASSEMBLED, payload={"step": state.step})

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
                    payload={"index": delta.index, "id": delta.id, "name": delta.name,
                             "arguments_delta": delta.arguments_delta},
                )

            if chunk.finish_reason is not None:
                last_finish_reason = chunk.finish_reason

            round_usage = merge_usage(round_usage, chunk.usage)

        state.add_usage(round_usage)
        tool_calls = _assemble_tool_calls(tool_call_meta, tool_json_fragments)
        tool_calls.sort(key=lambda tc: tc.id)  # 稳定顺序
        full_text = "".join(text_parts)
        _append_assistant(state, full_text, tool_calls)
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

        if not tool_calls:
            state.step += 1
            return

        call_tuples = [(tc.name, tc.arguments) for tc in tool_calls]
        batches = plan_batch(call_tuples, registry)
        yield LoopStreamEvent(
            event_type=EVENT_TOOL_BATCH_START,
            payload={"total": len(tool_calls), "batches": len(batches), "step": state.step},
        )

        call_map = {tc.name: tc for tc in tool_calls}
        for batch_idx, batch in enumerate(batches):
            yield LoopStreamEvent(
                event_type=EVENT_TOOL_GROUP_START,
                payload={"batch_index": batch_idx,
                         "tool_names": [n for n, _ in batch], "step": state.step},
            )

            tasks: list[asyncio.Task[tuple[ToolCall, ToolResult]]] = []
            for name, args in batch:
                async with sem:
                    tasks.append(
                        asyncio.create_task(
                            _execute_tool_safely(
                                registry,
                                budget,
                                ToolCall(
                                    id=call_map[name].id, name=name, arguments=args
                                ),
                            )
                        )
                    )
            # 注意：_execute_tool_safely 返回 ToolResult，这里按 call 顺序回填
            results = await asyncio.gather(*tasks)
            for (name, _), result in zip(batch, results):
                state.append_tool_result(
                    tool_result_message(
                        tool_use_id=call_map[name].id,
                        tool_name=name,
                        output=result.output or (result.error or ""),
                        is_error=not result.ok,
                    )
                )

            yield LoopStreamEvent(
                event_type=EVENT_TOOL_GROUP_END,
                payload={"batch_index": batch_idx, "tool_count": len(batch),
                         "step": state.step},
            )

        yield LoopStreamEvent(
            event_type=EVENT_TOOL_BATCH_END,
            payload={"total": len(tool_calls), "step": state.step},
        )

        state.clear_pending()
        state.step += 1

    yield LoopStreamEvent(
        event_type=EVENT_FINISH,
        payload={"stop_reason": state.stop_reason or "max_steps", "step": state.step},
    )


__all__ = ["schedule_overlapped_tools", "ToolExecutor", "execute_with_overlap"]
