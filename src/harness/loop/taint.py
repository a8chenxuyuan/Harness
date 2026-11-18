"""污染标记（Taint）追踪器。

Phase 7 自愈会在三种情况下标记污染：
1. dedup_warning —— 工具去重被拦
2. tool_repeated_failure —— 连续 3 次 tool 返回 ok=False（此时也会 stopping）
3. assistant_stuck —— 连续两条 assistant text 相似度 > 0.9

TaintTracker 是无状态工具类，所有读写都落在 AgentState.taint 上。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import AgentState


class TaintTracker:
    """污染标记的读写辅助类。

    所有方法都是纯静态的，不持有状态；实例化也可以，但没必要。
    """

    # --- 基础读写 ---------------------------------------------------------------

    @staticmethod
    def mark(state: AgentState, key: str, reason: str) -> None:
        """标记一个污染键。相同 key 覆盖，保证幂等。

        Args:
            state: AgentState 实例。
            key: 污染键名，如 "dedup_warning"、"assistant_stuck"。
            reason: 触发原因说明。
        """
        state.taint[key] = reason

    @staticmethod
    def has(state: AgentState, key: str) -> bool:
        """检查某个污染键是否存在。

        Args:
            state: AgentState 实例。
            key: 污染键名。

        Returns:
            True 表示该键已标记。
        """
        return key in state.taint

    @staticmethod
    def get(state: AgentState, key: str) -> str | None:
        """取某个污染键的原因，不存在返回 None。

        Args:
            state: AgentState 实例。
            key: 污染键名。

        Returns:
            原因字符串或 None。
        """
        return state.taint.get(key)

    @staticmethod
    def clear(state: AgentState, key: str | None = None) -> None:
        """清除污染标记。

        Args:
            state: AgentState 实例。
            key: 指定清哪一个；None 表示全部清除。
        """
        if key is None:
            state.taint.clear()
        else:
            state.taint.pop(key, None)

    # --- 传播到 volatile_context -------------------------------------------------

    @staticmethod
    def propagate(state: AgentState) -> None:
        """把当前所有 taint 合并进 state.volatile_context。

        ContextAssembler.assemble 会把 volatile_context 拼进 system prompt
        的末尾（或作为单独一条 system msg 附加），这样模型下一轮就能
        "看到" 自己已经被污染的状态，而不是盲目复读。

        Args:
            state: AgentState 实例。
        """
        if not state.taint:
            return
        existing = state.volatile_context.get("taint", {})
        if not isinstance(existing, dict):
            existing = {}
        existing.update(state.taint)
        state.volatile_context["taint"] = existing
