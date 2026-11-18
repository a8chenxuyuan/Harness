"""上下文窗口裁剪：从历史里挑出能塞进 max_tokens 的那一段。

Phase 8 的 SessionWindow 只做「选边界」——真正的装配还是 ContextAssembler
管的。window 在这里只关心三件事：哪些 entry 占上下文 token、窗口的起止
seq、以及剩余预算。

设计要点：
    - compaction entry 也算 token（它是旧 message 的摘要代表，必须占 prompt）
    - reset / custom 不占 token，窗口计算直接跳过
    - 从最新 entry 往前翻，而不是从最旧往后加——保证"最近的对话一定保留"
    - 硬阈值 max_tokens * 0.8 停下，给下一轮 volatile 留空间
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from ..context.token_budget import TokenBudget, TokenCounter, estimate_tokens
from .entry import SessionTreeEntry


@dataclass(frozen=True, slots=True)
class SessionWindow:
    """一次上下文裁剪后的窗口描述。

    Attributes:
        entries: 落在窗口内的 entry 引用（不复制，直接切片原 list）。
        first_kept_seq: 窗口里最早那条占上下文的 entry 的 seq。
        last_seq: 窗口里最新 entry 的 seq（通常就是 all_entries 最后一条）。
        budget_remaining: 本轮用完窗口后还剩多少 token 可给 volatile_context。
    """

    entries: list[SessionTreeEntry] = field(default_factory=list)
    first_kept_seq: int = 0
    last_seq: int = 0
    budget_remaining: int = 0


def _entry_token_count(entry: SessionTreeEntry, counter: TokenCounter) -> int:
    """单条 entry 占多少 token。

    - message entry：content 是 Msg.to_dict() 的字符串 JSON，按 canonical_json 算
    - compaction entry：只算 summary 字段本身的 token（它代表了被压缩掉的历史）
    - reset / custom：不占上下文 token
    """
    if entry.kind == "message":
        # entry.content 已经是 Msg.to_dict() 的结构，dump 成字符串再计数
        import json as _json

        return counter.count(_json.dumps(entry.content, ensure_ascii=False))
    if entry.kind == "compaction":
        summary = entry.content.get("summary", "")
        return counter.count(summary)
    return 0


def derive_window(
    all_entries: Iterable[SessionTreeEntry],
    prefix_tokens: int,
    max_tokens: int,
    counter: TokenCounter | None = None,
) -> SessionWindow:
    """从全量 entry 里切出能塞进 max_tokens 的窗口。

    算法：
        1. 从最新 entry 往旧的翻（从后往前遍历 list）
        2. message / compaction entry 累加 token，reset / custom 跳过
        3. 累加 token 达到 max_tokens * 0.8 - prefix_tokens 时停下
        4. 剩余 entry 不再占上下文，但仍保留在 SessionWindow.entries 里
           （让上层可以按 kind 特殊处理 reset/custom 信号）

    Args:
        all_entries: 已按 seq ASC 排序的全量 entry 列表。
        prefix_tokens: 稳定前缀已经占掉的 token，要先扣掉。
        max_tokens: 模型上下文窗口上限。
        counter: TokenCounter 实例；None 就用 estimate_tokens 粗算。

    Returns:
        填好的 SessionWindow。窗口为空（库空或全是 reset/custom）也会返回。
    """
    entries = list(all_entries)
    if not entries:
        return SessionWindow(entries=[], first_kept_seq=0, last_seq=0, budget_remaining=max_tokens)

    cnt = counter or TokenCounter()
    budget_for_history = int(max_tokens * 0.8) - prefix_tokens
    budget_for_history = max(budget_for_history, 0)

    kept_reversed: list[SessionTreeEntry] = []
    accumulated = 0
    first_kept_seq = 0

    # 从末尾往前翻
    for entry in reversed(entries):
        tokens = _entry_token_count(entry, cnt)
        if accumulated + tokens > budget_for_history and kept_reversed:
            # 窗口里已经至少塞了一条，再加就超了——停
            break
        kept_reversed.append(entry)
        accumulated += tokens
        first_kept_seq = entry.seq

    kept = list(reversed(kept_reversed))
    last_seq = entries[-1].seq if entries else 0

    return SessionWindow(
        entries=kept,
        first_kept_seq=first_kept_seq,
        last_seq=last_seq,
        budget_remaining=max_tokens - prefix_tokens - accumulated,
    )
