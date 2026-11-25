"""事件总线的核心数据结构。

EventType 枚举定义了 harness 运行时会发出的所有事件类型；
Event 是冻结 dataclass，保证同一条事件在传递过程中不被篡改。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """事件类型枚举。

    每个值都是 snake_case 字符串，与外部日志/指标系统的
    event_type 字段对齐。
    """

    # 装配层
    ASSEMBLED = "assembled"

    # 模型流式
    MODEL_STREAM_START = "model_stream_start"
    MODEL_CHUNK = "model_chunk"
    MODEL_STREAM_END = "model_stream_end"

    # 工具
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    TOOL_BATCH_START = "tool_batch_start"
    TOOL_BATCH_END = "tool_batch_end"

    # 会话生命周期
    SESSION_START = "session_start"
    SESSION_END = "session_end"

    # Phase 7 自愈
    TAINT_MARKED = "taint_marked"

    # 压缩
    COMPACTION_TRIGGERED = "compaction_triggered"


@dataclass(frozen=True)
class Event:
    """一条运行时事件。

    Attributes:
        type: 事件类型。
        session_id: 关联的会话。
        timestamp: 单调时钟时间戳（time.monotonic()），
            保证进程内递增，不受系统时钟回拨影响。
        payload: 事件附加数据，任意可序列化字典。
    """

    type: EventType
    session_id: str
    timestamp: float = field(default_factory=time.monotonic)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """导出可序列化字典，便于日志和指标系统消费。

        Returns:
            有序字典：type / session_id / timestamp / payload。
        """
        return {
            "type": self.type.value,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }
