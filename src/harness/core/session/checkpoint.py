"""CheckpointManager：保存 / 恢复 / 工具去重三件事。

核心流程：
    - save(): 从 AgentState.messages 批量写 message entry
    - load(): 全量读 entry → 按 seq 重建 AgentState
        message entry → state.messages
        compaction entry → volatile_context["compacted_ranges"]
        reset entry → 清控制字段（step / stopping / pending_tool_calls / taint）
    - completed_tool_calls(): 从 message entry 里提取 (tool_name, tool_args_json)
        集合，供 Phase 5 recovery 恢复时跳过已执行的工具

为什么不直接用 msgpy 的 msgpack 序列化 AgentState？
    - entry 一旦写入就必须"可读、可审计、可手动查询"——sqlite 里每行都能看到内容。
    - 四种 kind 带来的结构化重放能力是 msgpack 做不到的。
"""

from __future__ import annotations

import json
from typing import Any

from harness.core.loop.state import AgentState
from harness.common.message.msg import Msg

from .entry import SessionTreeEntry
from .store import SessionStore


class CheckpointManager:
    """AgentState 的会话层 checkpoint 管理器。

    依赖 SessionStore；compaction / window 是上层的事。
    """

    def __init__(self, store: SessionStore) -> None:
        """绑定一个 store 实例。

        Args:
            store: 底层 sqlite 存储。manager 不拥有 store 生命周期，调用方负责 close。
        """
        self._store = store

    # --- 保存 ------------------------------------------------------------------

    async def save(self, state: AgentState) -> list[SessionTreeEntry]:
        """把 AgentState.messages 全部写成 message entry。

        Args:
            state: 当前 AgentState。

        Returns:
            写入成功的 entry 列表（已分配好 seq）。
        """
        entries = [
            SessionTreeEntry(kind="message", content=msg.to_dict())
            for msg in state.messages
        ]
        return await self._store.append_many(entries)

    # --- 恢复 ------------------------------------------------------------------

    async def load(self, session_id: str = "default") -> AgentState:
        """从 store 读全量 entry，按 seq 重建成 AgentState。

        重放规则：
            1. message entry → Msg.from_dict() 追加到 state.messages
            2. compaction entry → 记进 state.volatile_context["compacted_ranges"]
               （给 ContextAssembler 看，哪些 seq 范围已经被摘要覆盖）
            3. reset entry → 清 state 的控制字段（step、stopping、pending、taint、
               tool_results、last_response_text），messages 不清

        Args:
            session_id: 会话标识，写进 AgentState.session_id 里。load 不按 id 过滤——
                sqlite 里所有 entry 都是同一个 session 的。

        Returns:
            重建好的 AgentState；库空则返回 state.messages = []。
        """
        all_entries = await self._store.get_all()

        state = AgentState(session_id=session_id)
        compacted_ranges: list[dict[str, Any]] = []

        for entry in all_entries:
            if entry.kind == "message":
                try:
                    msg = Msg.from_dict(entry.content)
                except Exception:
                    # 单条坏数据不应阻断整个恢复；跳过即可
                    continue
                state.messages.append(msg)
            elif entry.kind == "compaction":
                compacted_ranges.append(
                    {
                        "seq_start": entry.content.get("kept_seq_start"),
                        "seq_end": entry.content.get("kept_seq_end"),
                        "summary": entry.content.get("summary", ""),
                        "seq": entry.seq,
                    }
                )
            elif entry.kind == "reset":
                self._apply_reset(state, entry.content)
            # custom entry 暂不处理，留给业务扩展

        state.volatile_context["compacted_ranges"] = compacted_ranges
        return state

    @staticmethod
    def _apply_reset(state: AgentState, content: dict[str, Any]) -> None:
        """reset entry 的语义：清运行时控制字段，messages 继续累积。"""
        state.step = 0
        state.stopping = False
        state.stop_reason = None
        state.pending_tool_calls = []
        state.tool_results = []
        state.taint = {}
        state.last_response_text = ""

    # --- 工具去重 --------------------------------------------------------------

    async def completed_tool_calls(self) -> set[tuple[str, str]]:
        """提取已执行过的 (tool_name, tool_args_json) 集合。

        遍历所有 message entry 里 role="assistant" 的消息，取其 content
        中 type="tool_use" 的块。ToolUseBlock.input 就是模型给的原始参数，
        排序后 json.dumps 成规范串——保证同一份参数不管键插入顺序如何
        都生成相同哈希。

        这个集合在 Phase 5 recovery 恢复时用来"跳过已跑过的工具"。
        """
        entries = await self._store.get_all()
        done: set[tuple[str, str]] = set()

        for entry in entries:
            if entry.kind != "message":
                continue
            if entry.content.get("role") != "assistant":
                continue
            for block in entry.content.get("content", []):
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = block.get("name", "")
                try:
                    args_json = json.dumps(
                        block.get("input", {}),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                except (TypeError, ValueError):
                    args_json = "{}"
                done.add((name, args_json))

        return done
