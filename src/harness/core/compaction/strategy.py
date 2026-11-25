"""Phase 10：追加式 compaction 策略。

核心设计决策：
    - **绝不删历史**：compaction 只追加一条新 kind="compaction" 的 entry，
      旧 message entry 永远保留——恢复时可以按 seq 全量重建完整对话。
    - **stable_prefix 不变**：compaction entry 是 history 的一部分，不是
      stable_prefix 的一部分。下一轮 ContextAssembler.assemble 时，
      stable_prefix.prefix_hash 不会因为多了 compaction 而变化。
    - **摘要硬上限 16K**：压缩出来的 summary 本身也得塞进上下文，16K 是
      常见 LLM 窗口下合理的单条 compaction 大小。超了说明切点要换。
    - **可选模型**：有 Model 就用它生成自然语言摘要；没有就退回内置
      summarizer（每条消息 role + content 首 200 字符），保证离线环境也能工作。
"""

from __future__ import annotations

import json
from typing import Any

from harness.core.context.token_budget import estimate_tokens
from harness.common.message.content_block import ToolUseBlock
from harness.common.message.msg import Msg
from harness.core.model.base import Model
from harness.core.model.types import GenerateOptions
from harness.core.session.entry import SessionTreeEntry

from .summary import HARD_LIMIT, CompactionSummary


# 一条 compaction 默认压缩多少条 message。
# 5 条一组既能显著减 token，又不会把上下文压缩得太"粗"。
_DEFAULT_GROUP_SIZE = 5


def _fallback_summarize(messages: list[Msg]) -> str:
    """没有模型时的兜底摘要：role + content 首 200 字符拼接。

    Args:
        messages: 被压缩掉的原始消息列表。

    Returns:
        形如"user: 你好世界... | assistant: 我来帮你..."的纯文本。
    """
    chunks: list[str] = []
    for msg in messages:
        role = msg.role.value
        # 取所有文本块的拼接，再截前 200 字符
        text = msg.text()[:200]
        if not text and msg.role.value == "assistant":
            # assistant 消息可能只有 tool_use 没有 text——把工具名拼进去
            tool_names = [
                block.name
                for block in msg.content
                if isinstance(block, ToolUseBlock)
            ]
            text = f"[tool_calls: {', '.join(tool_names)}]"
        chunks.append(f"{role}: {text}")
    return " | ".join(chunks)


class CompactionStrategy:
    """追加式压缩策略。

    Attributes:
        max_summary_tokens: 摘要硬上限；默认 16_000，见 HARD_LIMIT 常量。
        model: 可选的摘要模型。None 走内置 summarizer。
        group_size: 默认一次压缩多少条 message。
    """

    def __init__(
        self,
        max_summary_tokens: int = HARD_LIMIT,
        model: Model | None = None,
        group_size: int = _DEFAULT_GROUP_SIZE,
    ) -> None:
        if max_summary_tokens <= 0:
            raise ValueError("max_summary_tokens 必须为正数")
        if group_size <= 0:
            raise ValueError("group_size 必须为正数")
        self.max_summary_tokens = max_summary_tokens
        self.model = model
        self.group_size = group_size

    # --- 公开入口 --------------------------------------------------------------

    async def compact(
        self,
        all_entries: list[SessionTreeEntry],
        threshold_seq: int,
    ) -> SessionTreeEntry:
        """选切点 + 生成摘要 + 返回一条 compaction entry。

        典型调用时机：ContextAssembler.evaluate() 说 compaction_required=True
        时，上层把当前全量 entry 和触发阈值 threshold_seq 传进来。

        Args:
            all_entries: 当前全量 entry（已按 seq ASC）。
            threshold_seq: 触发压缩的 seq 阈值。切点必须 <= threshold_seq，
                保证"最新的对话不被压"。

        Returns:
            一条 kind="compaction" 的 SessionTreeEntry。调用方负责 append 进 store。
        """
        # 1. 选切点：从 threshold_seq 往前数，挑 self.group_size 条 message entry
        to_compact, kept_seq_start, kept_seq_end = self._pick_slice(
            all_entries, threshold_seq
        )

        # 2. 生成摘要
        summary_text = await self._summarize(to_compact)

        # 3. 硬上限截断
        summary_text = self._enforce_limit(summary_text)

        # 4. 组装 compaction entry
        return SessionTreeEntry(
            kind="compaction",
            content={
                "summary": summary_text,
                "kept_seq_start": kept_seq_start,
                "kept_seq_end": kept_seq_end,
            },
        )

    # --- 内部 ------------------------------------------------------------------

    def _pick_slice(
        self,
        all_entries: list[SessionTreeEntry],
        threshold_seq: int,
    ) -> tuple[list[Msg], int, int]:
        """挑出要被压缩的 message 切片。

        规则：从 threshold_seq（含）往前找，最多 self.group_size 条 message entry。
        compaction / reset / custom entry 跳过。不足 group_size 就只压能压的。
        如果压根没有 message entry 要压，返回空切片和 0 seq——调用方自己判断要不要 append。
        """
        # 先拿到 <= threshold_seq 的所有 message entry
        candidates: list[SessionTreeEntry] = [
            e
            for e in all_entries
            if e.seq <= threshold_seq and e.kind == "message"
        ]
        if not candidates:
            return [], 0, 0

        # 从末尾往前挑 group_size 条（靠 threshold_seq 最近的那组先压）
        picked = candidates[-self.group_size :]
        start_seq = picked[0].seq
        end_seq = picked[-1].seq

        msgs: list[Msg] = []
        for entry in picked:
            try:
                msgs.append(Msg.from_dict(entry.content))
            except Exception:
                # 单条坏数据跳过
                continue

        return msgs, start_seq, end_seq

    async def _summarize(self, messages: list[Msg]) -> str:
        """生成摘要文本。有 model 就调 generate()，否则兜底。"""
        if not messages:
            return ""

        if self.model is None:
            return _fallback_summarize(messages)

        # 用模型做摘要：把所有消息拼成一个 system + user 的最小 prompt
        summary_prompt = self._build_summary_prompt(messages)
        prompt_messages = [
            Msg.from_dict(
                {
                    "role": "system",
                    "content": [
                        {"type": "text", "text": "你是一个会话压缩助手。请把下面的对话历史用一句话总结，保留关键事实和工具调用结果。"}
                    ],
                }
            ),
            Msg.from_dict(
                {
                    "role": "user",
                    "content": [{"type": "text", "text": summary_prompt}],
                }
            ),
        ]
        options = GenerateOptions(
            temperature=0.1,
            max_tokens=self.max_summary_tokens,
            stream=False,
        )
        try:
            response = await self.model.generate(prompt_messages, [], options)
            return response.text.strip()
        except Exception:
            # 模型调用失败回退内置 summarizer，不让压缩流程中断
            return _fallback_summarize(messages)

    @staticmethod
    def _build_summary_prompt(messages: list[Msg]) -> str:
        """把要压缩的消息拼成一段可直接丢给摘要模型的文本。"""
        parts: list[str] = []
        for msg in messages:
            role = msg.role.value
            text = msg.text()
            if not text:
                continue
            parts.append(f"[{role}] {text}")
        return "\n".join(parts)

    def _enforce_limit(self, summary: str) -> str:
        """摘要超 16K token 时按字符硬截断，尾部加 [truncated] 标记。"""
        if estimate_tokens(summary) <= self.max_summary_tokens:
            return summary
        # 粗略按字符截——token 估算本身就是字符级的，同尺度截断
        ratio = self.max_summary_tokens / max(1, estimate_tokens(summary))
        cut = int(len(summary) * ratio)
        return summary[:cut].rstrip() + "\n...[truncated]"

    # --- CompactionSummary 生产 ------------------------------------------------

    def build_summary(
        self,
        summary_text: str,
        seq_start: int,
        seq_end: int,
    ) -> CompactionSummary:
        """把生成好的摘要文本包装成 CompactionSummary（方便外部检查）。"""
        return CompactionSummary(
            summary=summary_text,
            original_seq_start=seq_start,
            original_seq_end=seq_end,
            hard_limit=self.max_summary_tokens,
        )
