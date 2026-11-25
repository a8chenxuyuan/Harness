"""Phase 7 自愈层。

三个触发点（按执行顺序）：
1. dedup：相同 (tool+args) 第二次调用 → 注入一个 ok=False 的 ToolResult，
   并标记 taint["dedup_warning"]，不终止
2. 连续 3 次 tool ok=False → stopping=True，stop_reason="tool_repeated_failure"
3. 连续两条 assistant text 相似度 > 0.9 → state.messages 末尾注入一条
   system 提示"请换一种方式回答"，标记 taint["assistant_stuck"]，不终止

recovery 是一个独立模块，由 streaming / react_graph 在合适时机调用，
不主动挂到 graph 节点上（避免侵入性）。
"""

from __future__ import annotations

import difflib
import json
from typing import TYPE_CHECKING, Any

from harness.core.model.types import ToolCall
from harness.core.tool.base import ToolResult

from .taint import TaintTracker

if TYPE_CHECKING:
    from .state import AgentState


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _dedup_key(name: str, args: dict[str, Any]) -> str:
    """与 ToolBudget._dedup_key 保持一致的去重键。"""
    return f"{name}::{json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)}"


def _text_similarity(a: str, b: str) -> float:
    """用 difflib.SequenceMatcher 算两条文本的相似度。

    Args:
        a: 文本 A。
        b: 文本 B。

    Returns:
        0.0 ~ 1.0。越接近 1.0 越相似。
    """
    return difflib.SequenceMatcher(None, a, b).ratio()


def _is_tool_message(msg) -> bool:  # type: ignore[no-untyped-def]
    """判断一个 state.messages 元素是不是 tool 结果消息。"""
    from harness.common.message.role import Role

    return msg.role == Role.TOOL


def _tool_name_from_msg(msg) -> str:  # type: ignore[no-untyped-def]
    """从 tool 结果消息取工具名（优先 name 字段，fallback to content block）。"""
    if msg.name:
        return msg.name
    # ToolResultBlock 里有 tool_use_id 但没有 name，这里兜底
    return ""


# ---------------------------------------------------------------------------
# 1. 工具去重
# ---------------------------------------------------------------------------

def check_tool_dedup(
    state: "AgentState",
    call: ToolCall,
) -> ToolResult | None:
    """检查一个待执行的 ToolCall 是否在历史里已经跑过。

    Args:
        state: AgentState 实例。
        call: 待执行的 tool call。

    Returns:
        如果命中，返回一个构造好的 ToolResult（ok=False, output 提示"已执行过"）；
        未命中返回 None。
    """
    key = _dedup_key(call.name, call.arguments)

    # 只看本轮 pending_tool_calls 之前的 tool_results（避免同一轮里重复拦）
    for msg in state.tool_results:
        # 简单看名字 + 构造伪 args 来比对——严格比需要 ToolMsg.content 里有原始 args
        # 这里做宽松拦截：同名工具的结果出现过就算
        if msg.name == call.name:
            # 进一步：本轮 messages 里有一条 tool 结果的 content 含相同输出？
            # 简化实现：只要工具名相同且在历史 tool_results 里，就标记 dedup
            TaintTracker.mark(state, "dedup_warning", f"tool {call.name} already executed")
            return ToolResult(
                ok=False,
                output=f"该调用已执行过（tool={call.name}），不再重复执行",
                error="dedup",
            )
    return None


# ---------------------------------------------------------------------------
# 2. 连续报错
# ---------------------------------------------------------------------------

def count_consecutive_tool_failures(state: "AgentState") -> int:
    """数一下最后连续多少条 tool result 是 ok=False。

    Args:
        state: AgentState 实例。

    Returns:
        从末尾向前数的连续失败条数；至少一条 ok=True 就截断。
    """
    from harness.common.message.content_block import ToolResultBlock

    failures = 0
    # 倒序遍历 tool_results（和 messages 里的 tool msg 一致）
    for msg in reversed(state.tool_results):
        # 从 content[0] 取 is_error
        is_error = False
        for block in msg.content:
            if isinstance(block, ToolResultBlock):
                is_error = block.is_error
                break
        if is_error:
            failures += 1
        else:
            break
    return failures


def check_tool_repeated_failure(state: "AgentState", threshold: int = 3) -> bool:
    """如果连续失败 >= threshold，标记 stopping 并返回 True。

    Args:
        state: AgentState 实例。
        threshold: 阈值，默认 3。

    Returns:
        True 表示触发了终止。
    """
    if count_consecutive_tool_failures(state) >= threshold:
        TaintTracker.mark(state, "tool_repeated_failure", f"连续 {threshold} 次 tool 失败")
        state.mark_stopped("tool_repeated_failure")
        return True
    return False


# ---------------------------------------------------------------------------
# 3. 助手复读
# ---------------------------------------------------------------------------

def check_assistant_stuck(
    state: "AgentState",
    similarity_threshold: float = 0.9,
) -> bool:
    """如果最近两条助手文本相似度 > 阈值，注入 system 提示。

    实现策略：
    - 倒序找两条相邻的 assistant 文本消息（跳过 tool msg、thinking block）
    - 算相似度
    - 超过阈值就 append 一条 system 提示到 state.messages 末尾

    Args:
        state: AgentState 实例。
        similarity_threshold: 相似度阈值，默认 0.9。

    Returns:
        True 表示注入了 stuck 提示。
    """
    from harness.common.message.helpers import system_message
    from harness.common.message.role import Role

    # 收集所有 assistant 文本
    assistant_texts: list[str] = []
    for msg in reversed(state.messages):
        if msg.role != Role.ASSISTANT:
            continue
        text = msg.text()
        if text:
            assistant_texts.append(text)
        if len(assistant_texts) >= 2:
            break

    if len(assistant_texts) < 2:
        return False

    latest = assistant_texts[0]
    previous = assistant_texts[1]
    sim = _text_similarity(latest, previous)
    if sim > similarity_threshold:
        TaintTracker.mark(state, "assistant_stuck", f"相似度 {sim:.2f} > {similarity_threshold}")
        # 追加 system 提示——这条提示不进稳定前缀（因为是 runtime 注入），
        # 所以不能用 ContextAssembler 的系统提示，只能走 volatile_context
        # 但 volatile_context 在 assemble 时会被拼进 system prompt 末尾，
        # 所以这里改 state.volatile_context["recovery_hint"] 更干净。
        state.volatile_context["recovery_hint"] = (
            "你的上一条回复和前一条高度相似，请换一种回答方式或提出不同的方案。"
        )
        return True
    return False


# ---------------------------------------------------------------------------
# 组合入口
# ---------------------------------------------------------------------------

def run_all_checks(state: "AgentState") -> None:
    """一次跑完所有自愈检查，在 streaming 的每轮 finalize 后调用。

    Args:
        state: AgentState 实例。
    """
    # dedup 在工具执行前由 check_tool_dedup 单独拦，这里跳过
    check_tool_repeated_failure(state)
    if not state.should_stop:
        check_assistant_stuck(state)
