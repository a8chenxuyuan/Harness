"""Phase 10：追加式 compaction 模块。

对外导出：
    - CompactionStrategy：核心压缩策略（可选摘要模型，有内置 summarizer 兜底）
    - CompactionSummary：摘要产物的数据模型 + replay_summary 回放入口

约束（写在这里，让上层 import 时一眼看到）：
    - compaction entry 是追加式的——绝不修改或删除任何已有 entry
    - stable_prefix.prefix_hash 不会因为多了 compaction entry 而变化
    - 摘要硬上限 16K token（见 compaction.summary.HARD_LIMIT）
"""

from .strategy import CompactionStrategy
from .summary import CompactionSummary, replay_summary

__all__ = [
    "CompactionStrategy",
    "CompactionSummary",
    "replay_summary",
]
