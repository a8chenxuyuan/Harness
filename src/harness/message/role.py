"""角色枚举：一条消息是谁说的。

整个框架只有四种角色，不允许扩展。新增角色会破坏前缀稳定，
因为模型供应商对 role 的枚举是封闭的。
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """消息角色。

    Attributes:
        SYSTEM: 系统提示，只出现在前缀最前面，会话内不变。
        USER: 用户输入。
        ASSISTANT: 模型输出，可能含文本、思考、工具调用。
        TOOL: 工具执行结果，必须通过 tool_use_id 对应一次调用。
    """

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

    def __str__(self) -> str:
        """返回原始字符串值，便于直接拼接与日志输出。"""
        return self.value
