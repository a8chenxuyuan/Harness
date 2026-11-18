"""SessionMemoryView：把 AgentState 的历史转换成 MemoryItem。

典型用途：会话结束后，把本轮对话自动 save 到长期记忆。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from harness.message.role import Role

from .base import MemoryItem, new_item_id

if TYPE_CHECKING:
    from harness.loop.state import AgentState


class SessionMemoryView:
    """从 AgentState.messages 抽取记忆的适配器。"""

    # --- 公共入口 --------------------------------------------------------------

    @staticmethod
    def from_state(state: "AgentState") -> list[MemoryItem]:
        """把 state.messages 里的 user / assistant 文本转成 MemoryItem。

        - 只取 Role.USER 和 Role.ASSISTANT 的文本块
        - 每条消息生成一个 MemoryItem，session_id 继承自 state.session_id
        - content 为空的消息跳过
        - system / tool 消息不进入长期记忆（它们要么是系统提示，要么是机器结果）

        Args:
            state: 当前 ReAct 循环状态。

        Returns:
            MemoryItem 列表；顺序与 state.messages 保持一致，时间戳用当前时间。
        """
        items: list[MemoryItem] = []
        now = time.time()
        session_id = state.session_id

        for msg in state.messages:
            if msg.role not in (Role.USER, Role.ASSISTANT):
                continue

            text = msg.text()
            if not text.strip():
                continue

            # assistant 消息带了 tool_use 的，我们也收，但把 tool_use 内容过滤掉
            # msg.text() 已只返回 TextBlock，天然正确

            items.append(
                MemoryItem(
                    item_id=new_item_id(),
                    text=text.strip(),
                    metadata={
                        "role": msg.role.value,
                        "source": "session",
                    },
                    created_at=now,
                    session_id=session_id,
                )
            )
        return items

    @staticmethod
    def from_messages(
        messages: list,
        session_id: str = "",
    ) -> list[MemoryItem]:
        """直接从 Msg 列表抽取（不需要 AgentState 时用）。"""
        items: list[MemoryItem] = []
        now = time.time()
        for msg in messages:
            if getattr(msg, "role", None) not in (Role.USER, Role.ASSISTANT):
                continue
            text = msg.text() if hasattr(msg, "text") else ""
            if not text.strip():
                continue
            items.append(
                MemoryItem(
                    item_id=new_item_id(),
                    text=text.strip(),
                    metadata={"role": msg.role.value, "source": "raw"},
                    created_at=now,
                    session_id=session_id,
                )
            )
        return items
