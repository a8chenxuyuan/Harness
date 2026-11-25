"""ReAct 循环（Phase 5-7）对外导出。

提供：
- AgentState / 运行时状态
- run_loop / run_loop_with_events / build_graph —— 三种入口
- LoopStreamEvent / run_with_stream —— 流式事件
- Phase 7: TaintTracker / interrupt / resume / run_all_checks
"""

from .interrupt import interrupt, is_interrupted, resume
from .react_graph import build_graph, run_loop, run_loop_with_events
from .recovery import run_all_checks
from .state import AgentState
from .streaming import (
    EVENT_ASSEMBLED,
    EVENT_ERROR,
    EVENT_FINISH,
    EVENT_OVERLAP_SCHEDULED,
    EVENT_TEXT_DELTA,
    EVENT_TOOL_BATCH_END,
    EVENT_TOOL_BATCH_START,
    EVENT_TOOL_CALL_DELTA,
    EVENT_TOOL_END,
    EVENT_TOOL_GROUP_END,
    EVENT_TOOL_GROUP_START,
    EVENT_TOOL_START,
    LoopStreamEvent,
    run_with_stream,
)
from .taint import TaintTracker

__all__ = [
    # state
    "AgentState",
    # graph / runner
    "build_graph",
    "run_loop",
    "run_loop_with_events",
    # streaming
    "LoopStreamEvent",
    "run_with_stream",
    # event types
    "EVENT_ASSEMBLED",
    "EVENT_ERROR",
    "EVENT_FINISH",
    "EVENT_OVERLAP_SCHEDULED",
    "EVENT_TEXT_DELTA",
    "EVENT_TOOL_BATCH_END",
    "EVENT_TOOL_BATCH_START",
    "EVENT_TOOL_CALL_DELTA",
    "EVENT_TOOL_END",
    "EVENT_TOOL_GROUP_END",
    "EVENT_TOOL_GROUP_START",
    "EVENT_TOOL_START",
    # Phase 7: taint / interrupt / recovery
    "TaintTracker",
    "interrupt",
    "is_interrupted",
    "resume",
    "run_all_checks",
]
