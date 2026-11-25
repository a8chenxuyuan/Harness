"""Phase 6 工具执行器——独立于 streaming 的封装层。

ToolExecutor 从 streaming.py 里的同名实现独立出来，方便上层直接调用：
不依赖 ReAct 循环，只负责"给一批 (tool_name, args)，返回 ToolResult 列表"。

execute_with_overlap 也独立提供一份薄包装——它消费 model.stream 的 ChatChunk
迭代器，每拿到完整的 tool_call 就丢进队列并发执行，边等模型 finish 边
产出 LoopStreamEvent 流。
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, AsyncIterator

from harness.core.model.types import ChatChunk, ToolCall
from harness.core.tool.base import ToolResult
from harness.core.tool.budget import ToolBudget

from harness.core.loop.streaming import (
    EVENT_OVERLAP_SCHEDULED,
    EVENT_TOOL_GROUP_END,
    EVENT_TOOL_GROUP_START,
    LoopStreamEvent,
    _execute_tool_safely,
    _new_tool_call_fragments,
    _new_tool_call_meta,
)

if TYPE_CHECKING:
    from harness.core.tool.registry import ToolRegistry


class ToolExecutor:
    """Phase 6 并行工具执行器。

    内部用 admission.plan_batch 分批，批内 asyncio.gather + Semaphore 限并发，
    批间串行。

    Attributes:
        registry: 工具注册表。
        budget: 预算器。
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
        """执行一批工具调用，按 admission 结果分批。

        Args:
            calls: (tool_name, args_dict) 列表。

        Returns:
            ToolResult 列表，顺序与输入 calls 对应。
        """
        from harness.core.tool.admission import plan_batch

        batches = plan_batch(calls, self.registry)
        sem = asyncio.Semaphore(self.concurrency)
        all_results: list[ToolResult] = []

        for batch in batches:
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

    async def execute_single(
        self,
        name: str,
        args: dict[str, Any],
    ) -> ToolResult:
        """执行单个工具。

        Args:
            name: 工具名。
            args: 参数字典。

        Returns:
            ToolResult。
        """
        (result,) = await self.execute_batch([(name, args)])
        return result


async def execute_with_overlap(
    chunk_stream: AsyncIterator[ChatChunk],
    registry: "ToolRegistry",
    budget: ToolBudget | None = None,
    concurrency: int = 4,
    step: int = 0,
) -> AsyncIterator[LoopStreamEvent]:
    """独立于 AgentState 的重叠执行：消费 ChatChunk 流，一拿到完整 tool_call 就并发执行。

    与 streaming.py 里的 execute_with_overlap 不同——这个版本**不**依赖 AgentState，
    调用方负责把执行结果写入自己的 state。返回的 LoopStreamEvent 里 payload 含
    完整的 ToolCall 和 ToolResult。

    Args:
        chunk_stream: model.stream 的 ChatChunk 迭代器。
        registry: 工具注册表。
        budget: 预算器，None 则新建。
        concurrency: 最大并发。
        step: 当前循环轮次，仅用于日志 payload。

    Yields:
        LoopStreamEvent，包括 tool_group_start / tool_group_end / overlap_scheduled。
    """
    from harness.core.tool.admission import plan_batch

    budget = budget or ToolBudget()
    sem = asyncio.Semaphore(concurrency)

    tool_json_fragments = _new_tool_call_fragments()
    tool_call_meta = _new_tool_call_meta()
    # 完整收集到的 tool_calls（finish_reason 到来后 flush）
    complete_calls: list[ToolCall] = []

    # 流式消费，累积 tool_call delta
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

        # finish_reason 到来时 flush 所有已知 tool_call
        if chunk.finish_reason is not None:
            for idx, meta in tool_call_meta.items():
                if not meta.id or not meta.name:
                    continue
                raw_json = "".join(tool_json_fragments.get(idx, []))
                try:
                    arguments = json.loads(raw_json) if raw_json else {}
                except json.JSONDecodeError:
                    arguments = {"__raw__": raw_json}
                complete_calls.append(
                    ToolCall(id=meta.id, name=meta.name, arguments=arguments)
                )
                yield LoopStreamEvent(
                    event_type=EVENT_OVERLAP_SCHEDULED,
                    payload={"tool_name": meta.name, "step": step},
                )

    if not complete_calls:
        return

    # admission 分批 + gather 执行
    batches = plan_batch([(c.name, c.arguments) for c in complete_calls], registry)
    call_map = {tc.name: tc for tc in complete_calls}

    for batch_idx, batch in enumerate(batches):
        yield LoopStreamEvent(
            event_type=EVENT_TOOL_GROUP_START,
            payload={
                "batch_index": batch_idx,
                "tool_names": [n for n, _ in batch],
                "step": step,
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

        results = await asyncio.gather(*tasks)

        yield LoopStreamEvent(
            event_type=EVENT_TOOL_GROUP_END,
            payload={
                "batch_index": batch_idx,
                "tool_count": len(batch),
                "step": step,
                "results": [
                    {
                        "tool_call": {"name": r[0].name, "arguments": r[1]},
                        "tool_result": r[2].model_dump(),
                    }
                    for r in results
                ],
            },
        )
