"""消息层：统一的消息与内容块表示。

对外只暴露这些名字，其余实现细节不导出。
"""

from .canonical import canonical_bytes, canonical_json, sorted_deep
from .content_block import (
    BlockBase,
    ContentBlock,
    ImageBlock,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from .helpers import (
    assistant_message,
    image_message,
    system_message,
    tool_result_message,
    user_message,
)
from .msg import Msg
from .role import Role

__all__ = [
    "BlockBase",
    "ContentBlock",
    "ImageBlock",
    "Msg",
    "Role",
    "TextBlock",
    "ThinkingBlock",
    "ToolResultBlock",
    "ToolUseBlock",
    "assistant_message",
    "canonical_bytes",
    "canonical_json",
    "image_message",
    "sorted_deep",
    "system_message",
    "tool_result_message",
    "user_message",
]
