"""压缩摘要的数据模型与回放入口。

CompactionSummary 是 strategy.py 生成 compaction entry 时产出的结构，
replay_summary 则是上层（ContextAssembler / 调试工具）按 seq 重放时
需要的一个极简入口——从 compaction entry 里把 summary 取回来。

为什么单独一个文件？
    - summary 是"压缩产物"的单一职责：strategy 负责生成，这里负责存和取。
    - replay_summary 的存在让上层不需要知道 content 的精确 schema。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..context.token_budget import estimate_tokens
from ..session.entry import SessionTreeEntry

# 16K 硬上限的意义：压缩摘要本身也必须塞进上下文，16K 是常见 LLM 上下文
# 窗口下、一条 compaction entry 占得合理又不会被 prompt 吃掉太多的上限。
# 如果一条 compaction 超过 16K，说明切点选得太靠前了——应该换个切点重切。
HARD_LIMIT: int = 16_000


@dataclass(frozen=True, slots=True)
class CompactionSummary:
    """一条压缩摘要的元数据 + 文本。

    Attributes:
        summary: 已压缩的自然语言文本。
        original_seq_start: 被压缩掉的旧 entry 的起始 seq（含）。
        original_seq_end: 被压缩掉的旧 entry 的结束 seq（含）。
        token_count: 摘要自身的 token 数（estimate_tokens 粗算）。
        hard_limit: 16K 硬上限，超过说明压缩做得太粗。
    """

    summary: str
    original_seq_start: int
    original_seq_end: int
    token_count: int = field(default=0)
    hard_limit: int = HARD_LIMIT

    def __post_init__(self) -> None:
        if not self.token_count:
            # frozen dataclass 用 object.__setattr__ 在 post_init 里补默认值
            object.__setattr__(self, "token_count", estimate_tokens(self.summary))

    @property
    def is_truncated(self) -> bool:
        """摘要是否在压缩时被截断过（超过硬上限）。"""
        return len(self.summary) > 0 and estimate_tokens(self.summary) >= self.hard_limit


def replay_summary(entry: SessionTreeEntry) -> str:
    """从一条 kind="compaction" 的 entry 里取出摘要文本。

    Args:
        entry: 必须是 compaction entry；其他 kind 返回空串。

    Returns:
        entry.content["summary"]；没有则返回空串。
    """
    if entry.kind != "compaction":
        return ""
    return entry.content.get("summary", "")
