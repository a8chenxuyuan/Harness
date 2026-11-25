"""会话层的「单条记录」数据模型。

一条 SessionTreeEntry 就是写进 sqlite 的一行：有唯一 entry_id、
全局递增的 seq、四种 kind 之一、以及随 kind 变化的 content 字典。

不可变（frozen dataclass）——一旦 append 进 SessionStore 就永远不改，
恢复时按 seq 重放，compaction 也是追加一条新 kind="compaction" 的
entry，绝不删历史。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

EntryKind = Literal["message", "compaction", "reset", "custom"]
"""四种 entry 类型，覆盖 Phase 8-10 的所有持久化场景。"""


@dataclass(frozen=True, slots=True)
class SessionTreeEntry:
    """会话持久化层的不可变记录。

    Attributes:
        entry_id: 每条 entry 的 UUID，用作 sqlite 主键。
        seq: 全局递增序号。恢复时按 seq ASC 重放，保证顺序。
        kind: 四种类型，决定 content 的 schema。
        content: 随 kind 变化的 payload 字典：
            - message: Msg.to_dict()
            - compaction: {"summary": str, "kept_seq_start": int, "kept_seq_end": int}
            - reset: {"reason": str}
            - custom: {"type": str, "payload": Any} 扩展位
        created_at: monotonic 时间戳，仅用于日志/排序，不参与比较。
    """

    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    seq: int = 0
    kind: EntryKind = "message"
    content: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)

    # --- 序列化 ----------------------------------------------------------------

    def to_row(self) -> tuple[str, int, str, str, float]:
        """把 entry 展开成 sqlite 可直接 INSERT 的一行。

        Returns:
            (entry_id, seq, kind, content_json, created_at) 元组。
        """
        return (
            self.entry_id,
            self.seq,
            self.kind,
            json.dumps(self.content, ensure_ascii=False, sort_keys=True),
            self.created_at,
        )

    @classmethod
    def from_row(cls, row: tuple[str, int, str, str, float]) -> "SessionTreeEntry":
        """从 sqlite 读回的一行还原 entry。

        Args:
            row: sqlite3.Row 或同结构 tuple。

        Returns:
            校验通过的 SessionTreeEntry 实例。
        """
        entry_id, seq, kind, content_json, created_at = row
        content = json.loads(content_json) if content_json else {}
        return cls(
            entry_id=entry_id,
            seq=seq,
            kind=kind,  # type: ignore[arg-type]
            content=content,
            created_at=created_at,
        )

    # --- 便捷查询 --------------------------------------------------------------

    @property
    def is_message(self) -> bool:
        """是不是普通对话消息（占上下文 token）。"""
        return self.kind == "message"

    @property
    def is_compaction(self) -> bool:
        """是不是压缩摘要（也占上下文 token）。"""
        return self.kind == "compaction"

    @property
    def occupies_context(self) -> bool:
        """这条 entry 会不会出现在下一轮 ContextAssembler 里。

        message 和 compaction 占上下文；reset / custom 只是控制信号，
        重放时要按 kind 特殊处理，但不进模型 prompt。
        """
        return self.kind in ("message", "compaction")
