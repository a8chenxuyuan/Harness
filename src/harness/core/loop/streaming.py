"""流式 ReAct runner（Phase 5 基础）。

保留：事件常量 + LoopStreamEvent、run_with_stream（串行版）、
工具安全/串行执行与消息组装辅助。

Phase 6 的重叠与并发执行已拆到 ``.overlap``，文件末尾做 re-export，
保证既有 ``from .streaming import execute_with_overlap`` 路径不变。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator

from harness.common.message.content_block import ToolUseBlock
from harness.common.message.helpers import assistant_message, tool_result_message
from harness.core.model.types import GenerateOptions, ToolCall, Usage, merge_usage
from harness.core.tool.base import ToolResult
from harness.core.tool.budget import ToolBudget

if TYPE_CHECKING:
    from harness.core.model.base import Model
    from harness.core.tool.registry import ToolRegistry

from .state import AgentState

# ---------------------------------------------------------------------------
# 事件类型常量
# ---------------------------------------------------------------------------

EVENT_TEXT_DELTA = "text_delta"
EVENT_TOOL_CALL_DELTA = "tool_call_delta"
EVENT_FINISH = "finish"
EVENT_TOOL_START = "tool_start"
EVENT_TOOL_END = "tool_end"
EVENT_ASSEMBLED = "assembled"
EVENT_ERROR = "error"

# Phase 6 事件（由 overlap 产出，这里保留常量定义避免循环 import）
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
    """

    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _new_tool_call_fragments() -> dict[int, list[str]]:
    """初始化 tool_call delta 累积器。"""
    return {}


def _new_tool_call_meta() -> dict[int, ToolCall]:
    """初始化 tool_call 元信息累积器（id / name 按 index）。"""
    return {}


def _assemble_tool_calls(
    meta: dict[int, ToolCall], fragments: dict[int, list[str]]
) -> list[ToolCall]:
    """把攒好的 id/name + JSON 片段拼成完整 ToolCall 列表。"""
    calls: list[ToolCall] = []
    for idx, item in meta.items():
        raw_json = "".join(fragments.get(idx, []))
        try:
            arguments = json.loads(raw_json) if raw_json else {}
        except json.JSONDecodeError:
            arguments = {"__raw__": raw_json}
        calls.append(ToolCall(id=item.id, name=item.name, arguments=arguments))
    return calls


def _append_assistant(
    state: AgentState, text: str, tool_calls: list[ToolCall]
) -> None:
    """把本轮 assistant 消息（文本 + tool_use）写入 state。"""
    if not tool_calls and not text:
        return
    tool_uses = [
        ToolUseBlock(id=tc.id, name=tc.name, input=tc.arguments) for tc in tool_calls
    ]
    state.messages.append(
        assistant_message(text=text or None, tool_uses=tool_uses or None)
    )
    state.last_response_text = text


async def _execute_tool_safely(
    registry: "ToolRegistry",
    budget: ToolBudget,
    call: ToolCall,
) -> ToolResult:
    """执行单个工具，处理去重、异常捕获和预算截断。

    即使工具抛异常也返回 ``ok=False`` 的 ToolResult，绝不向上抛。
    """
    cached = budget.check_dedup(call.name, call.arguments)
    if cached is not None:
        return cached

    try:
        tool = registry.get(call.name)
    except KeyError as exc:
        return ToolResult(ok=False, output="", error=f"未知工具: {call.name} ({exc})")

    start = time.monotonic()
    try:
        result = await tool.execute(**call.arguments)
    except Exception as exc:  # noqa: BLE001 - 工具抛什么都要吞掉
        elapsed_ms = (time.monotonic() - start) * 1000
        budget.record_dedup(
            call.name,
            call.arguments,
            ToolResult(ok=False, output="", error=str(exc), execution_time_ms=elapsed_ms),
        )
        return ToolResult(
            ok=False, output="", error=str(exc), execution_time_ms=elapsed_ms
        )

    elapsed_ms = (time.monotonic() - start) * 1000
    truncated = budget.wrap_result(result)
    budget.record_dedup(call.name, call.arguments, truncated)
    if truncated.execution_time_ms == 0.0:
        truncated = truncated.model_copy(update={"execution_time_ms": elapsed_ms})
    return truncated


async def _execute_tool_list_serial(
    state: AgentState,
    registry: "ToolRegistry",
    budget: ToolBudget,
    calls: list[ToolCall],
) -> list[tuple[ToolCall, ToolResult]]:
    """串行执行一批 tool_call，每发一条就写一条 ToolMsg。"""
    results: list[tuple[ToolCall, ToolResult]] = []
    for call in calls:
        result = await _execute_tool_safely(registry, budget, call)
        results.append((call, result))
        state.append_tool_result(
            tool_result_message(
                tool_use_id=call.id,
                tool_name=call.name,
                output=result.output or (result.error or ""),
                is_error=not result.ok,
            )
        )
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

    每轮：model.stream → 发 delta 事件 → finish 时组装 ChatResponse
    → 有 tool_calls 就串行执行 → 继续；否则终止。
    """
    while not state.should_stop:
        opts = GenerateOptions()
        text_parts: list[str] = []
        tool_json_fragments = _new_tool_call_fragments()
        tool_call_meta = _new_tool_call_meta()
        last_finish_reason = "stop"
        round_usage = Usage()

        yield LoopStreamEvent(
            event_type=EVENT_ASSEMBLED,
            payload={"step": state.step, "session_id": state.session_id},
        )

        try:
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

                round_usage = merge_usage(round_usage, chunk.usage)
        except Exception as exc:  # noqa: BLE001
            yield LoopStreamEvent(
                event_type=EVENT_ERROR,
                payload={"error": str(exc), "step": state.step},
            )
            state.mark_stopped(f"model_error: {exc}")
            return

        state.add_usage(round_usage)

        tool_calls = _assemble_tool_calls(tool_call_meta, tool_json_fragments)
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
            # 助手没发 tool_call → 正常结束，必须置终止信号
            state.step += 1
            state.mark_stopped("final_answer")
            return

        state.clear_pending()
        state.step += 1

    yield LoopStreamEvent(
        event_type=EVENT_FINISH,
        payload={
            "stop_reason": state.stop_reason or "max_steps",
            "step": state.step,
        },
    )


# ---------------------------------------------------------------------------
# Phase 6 符号再导出（保持既有 import 路径）
# ---------------------------------------------------------------------------

from .overlap import (  # noqa: E402,F401
    ToolExecutor,
    execute_with_overlap,
    schedule_overlapped_tools,
)

__all__ = [
    "LoopStreamEvent", "run_with_stream", "schedule_overlapped_tools",
    "execute_with_overlap", "ToolExecutor",
    "EVENT_TEXT_DELTA", "EVENT_TOOL_CALL_DELTA", "EVENT_FINISH",
    "EVENT_TOOL_START", "EVENT_TOOL_END", "EVENT_ASSEMBLED", "EVENT_ERROR",
    "EVENT_TOOL_GROUP_START", "EVENT_TOOL_GROUP_END", "EVENT_OVERLAP_SCHEDULED",
    "EVENT_TOOL_BATCH_START", "EVENT_TOOL_BATCH_END",
]
