"""事件总线（Phase 11）。

对外只暴露 Event / EventType / EventBus 和全局 get_event_bus()。
"""

from .bus import EventBus, get_event_bus
from .types import Event, EventType

__all__ = [
    "Event",
    "EventBus",
    "EventType",
    "get_event_bus",
]
