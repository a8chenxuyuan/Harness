"""循环中断与恢复工具函数。

Phase 7 外部调用 interrupt(state, reason) 即可立即终止图迭代；
恢复时调 resume(state)。实现就是对 AgentState.stopping / stop_reason
的简单封装，单独抽文件是为了给 LangGraph 的 StateGraph 节点
提供一个统一、可读的中断入口。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import AgentState


def interrupt(state: AgentState, reason: str = "user_interrupt") -> None:
    """立即中断当前图迭代。

    调完之后，LangGraph 的条件边检测到 state.stopping=True 就会直接
    跳到 END；简单 runner 的 while 循环也会因为 should_stop=True 退出。

    Args:
        state: AgentState 实例。
        reason: 中断原因字符串，写入 stop_reason 便于日志排查。
    """
    state.stopping = True
    state.stop_reason = reason


def is_interrupted(state: AgentState) -> bool:
    """查询当前状态是否处于中断/终止态。

    Args:
        state: AgentState 实例。

    Returns:
        True 表示 stopping=True。
    """
    return state.stopping


def resume(state: AgentState) -> None:
    """清除 stopping 标志，让图可以继续下一轮。

    典型场景：用户手动恢复一个被 user_interrupt 停掉的会话；
    或者 Phase 7 recovery 在阻断后决定继续。

    Args:
        state: AgentState 实例。
    """
    state.stopping = False
    state.stop_reason = None
