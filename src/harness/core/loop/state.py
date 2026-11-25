"""ReAct 循环的运行时状态模型。

AgentState 是整条 ReAct 循环（Phase 5-7）流转的唯一状态容器：
- 完整对话历史 messages 含 tool 结果
- step / max_steps 控制轮次
- stopping / stop_reason 承载中断与自愈终止信号
- taint 存放污染标记（Phase 7 自愈）
- pending_tool_calls / tool_results 桥接 model 输出与 tools 执行
- volatile_context 每轮传给 ContextAssembler 注入 system prompt
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from harness.common.message.msg import Msg
from harness.core.model.types import ToolCall


class AgentState(BaseModel):
    """ReAct 循环的运行时状态。

    所有 Phase 5-7 的节点（assemble / model / tools / finalize /
    recovery）都围绕同一个 AgentState 读写——这既是 LangGraph
    StateGraph 的 state 类型，也是简单 while-runner 的状态容器。

    Attributes:
        messages: 完整对话历史，含 system / user / assistant / tool 消息。
        step: 当前轮次，0-based。每次 finalize 后 +1。
        max_steps: 循环硬上限。step >= max_steps 时自动终止。
        stopping: 外部中断或内部终止信号。True 时 graph 直接跳到 END。
        stop_reason: stopping 的原因字符串（如 "tool_repeated_failure"、
            "user_interrupt"、"max_steps"），None 表示尚未停止。
        taint: 污染标记字典，key 是标记名（如 "dedup_warning"），value 是原因。
        pending_tool_calls: 本轮 model 刚发出、还没执行的 ToolCall 列表。
        tool_results: 已执行的工具结果（ToolMsg 的 role=TOOL），与 messages
            里的 tool msg 保持一致，但单独列方便 Phase 7 recovery 查询。
        last_response_text: 上一轮助手的纯文本输出（不含 tool_call），
            供 recovery 做"助手复读"相似度检查。
        session_id: 会话标识，传给 ContextAssembler 与 EventBus。
        volatile_context: 每轮临时信息（当前时间等），assemble 时注入。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    messages: list[Msg] = Field(default_factory=list)
    step: int = 0
    max_steps: int = 50
    stopping: bool = False
    stop_reason: str | None = None

    taint: dict[str, str] = Field(default_factory=dict)

    pending_tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[Msg] = Field(default_factory=list)

    last_response_text: str = ""
    session_id: str = "default"
    volatile_context: dict[str, Any] = Field(default_factory=dict)

    # --- 便捷查询 -----------------------------------------------------------------

    @property
    def hit_max_steps(self) -> bool:
        """是否已达到轮次上限。"""
        return self.step >= self.max_steps

    @property
    def should_stop(self) -> bool:
        """是否应该终止循环（stopping 或 max_steps）。"""
        return self.stopping or self.hit_max_steps

    def mark_stopped(self, reason: str) -> None:
        """标记终止并写入 stop_reason。

        Args:
            reason: 终止原因字符串。
        """
        self.stopping = True
        self.stop_reason = reason

    def clear_pending(self) -> None:
        """清空 pending_tool_calls（finalize 节点调用）。"""
        self.pending_tool_calls = []

    def append_tool_result(self, tool_msg: Msg) -> None:
        """追加一个 tool 结果到 tool_results 和 messages。

        Args:
            tool_msg: role=TOOL 的消息。
        """
        self.tool_results.append(tool_msg)
        self.messages.append(tool_msg)
