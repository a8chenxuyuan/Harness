"""token 计数与上下文预算。

唯一职责：给出「这轮请求占了多少 token、要不要压缩」的结论。

计数精度说明：
    tiktoken 需要下载编码表，离线环境会失败。因此这里优先用 tiktoken，
    不可用时降级为字符估算（中日韩字符按 1 token、其余按 4 字符 1 token）。
    降级只影响阈值判断的精度，不影响前缀字节的稳定性。
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from ..message.canonical import canonical_json
from ..message.msg import Msg

_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x3000, 0x303F),
    (0x3040, 0x30FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0xFF00, 0xFFEF),
)
"""按 token 效率约为「1 字符 1 token」的字符区间，主要是中日韩标点与汉字。"""


def _is_cjk(character: str) -> bool:
    """判断单个字符是否属于高 token 密度的东亚字符。

    Args:
        character: 单个字符。

    Returns:
        属于东亚字符区间时为 True。
    """
    code_point = ord(character)
    return any(low <= code_point <= high for low, high in _CJK_RANGES)


def estimate_tokens(text: str) -> int:
    """不依赖分词器估算 token 数。

    Args:
        text: 任意文本。

    Returns:
        东亚字符各计 1，其余字符每 4 个计 1（向上取整）。
    """
    cjk_count = sum(1 for character in text if _is_cjk(character))
    other_count = len(text) - cjk_count
    return cjk_count + (other_count + 3) // 4


class TokenCounter:
    """token 计数器，优先 tiktoken，失败则降级估算。

    唯一职责：把文本换算成 token 数。不做截断、不做预算判断。
    """

    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        self._encoding_name = encoding_name
        self._encoding: object | None = None
        self._resolved = False

    def _resolve_encoding(self) -> object | None:
        """尝试加载 tiktoken 编码表，只尝试一次。

        Returns:
            可用的编码对象；不可用时为 None。
        """
        if self._resolved:
            return self._encoding
        self._resolved = True
        try:
            import tiktoken  # 延迟导入：未安装或离线时直接降级

            self._encoding = tiktoken.get_encoding(self._encoding_name)
        except Exception:  # noqa: BLE001 - 任何加载失败都走估算，不影响主流程
            self._encoding = None
        return self._encoding

    @property
    def backend(self) -> str:
        """返回当前实际使用的计数方式，用于在指标里标注数据来源。

        Returns:
            `tiktoken` 或 `estimate`。
        """
        return "tiktoken" if self._resolve_encoding() is not None else "estimate"

    def count(self, text: str) -> int:
        """统计一段文本的 token 数。

        Args:
            text: 任意文本。

        Returns:
            token 数量；空文本为 0。
        """
        if not text:
            return 0
        encoding = self._resolve_encoding()
        if encoding is None:
            return estimate_tokens(text)
        return len(encoding.encode(text, disallowed_special=()))  # type: ignore[attr-defined]

    def count_messages(self, messages: Sequence[Msg]) -> int:
        """统计一组消息的 token 数，按规范 JSON 计算。

        Args:
            messages: 消息序列。

        Returns:
            所有消息规范序列化后的 token 总数。
        """
        return sum(self.count(canonical_json(message.to_dict())) for message in messages)


class TokenBudgetStatus(BaseModel):
    """一轮装配的预算结论。

    Attributes:
        max_context_tokens: 上下文窗口上限。
        current_tokens: 本轮装配后的总 token 数。
        compaction_threshold: 触发压缩的阈值。
        compaction_required: 是否必须压缩。
        usage_ratio: 已用比例。
        counter_backend: 计数来源（tiktoken / estimate）。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_context_tokens: int
    current_tokens: int
    compaction_threshold: int
    compaction_required: bool
    usage_ratio: float = Field(ge=0.0)
    counter_backend: str


class TokenBudget:
    """上下文预算器。

    唯一职责：根据上限与阈值判断是否需要压缩，并给出可核对的数值。
    真正的压缩由 compaction 层执行，这里只发信号。
    """

    def __init__(
        self,
        max_context_tokens: int = 32_000,
        compaction_ratio: float = 0.8,
        counter: TokenCounter | None = None,
    ) -> None:
        if max_context_tokens <= 0:
            raise ValueError("max_context_tokens 必须为正数")
        if not 0 < compaction_ratio <= 1:
            raise ValueError("compaction_ratio 必须落在 (0, 1]")
        self._max_context_tokens = max_context_tokens
        self._compaction_ratio = compaction_ratio
        self._counter = counter or TokenCounter()

    @property
    def counter(self) -> TokenCounter:
        """返回内部计数器，供装配器复用，避免重复加载编码表。"""
        return self._counter

    @property
    def max_context_tokens(self) -> int:
        """上下文窗口上限。"""
        return self._max_context_tokens

    @property
    def compaction_threshold(self) -> int:
        """触发压缩的 token 阈值（向下取整，宁可早压不可超窗）。"""
        return int(self._max_context_tokens * self._compaction_ratio)

    def evaluate(
        self,
        prefix_tokens: int,
        history_tokens: int,
        volatile_tokens: int = 0,
    ) -> TokenBudgetStatus:
        """汇总各层 token 并判断是否需要压缩。

        Args:
            prefix_tokens: 稳定前缀 token 数。
            history_tokens: 历史消息 token 数。
            volatile_tokens: 本轮临时上下文 token 数。

        Returns:
            包含总量、阈值与压缩信号的结论。
        """
        total = max(0, prefix_tokens) + max(0, history_tokens) + max(0, volatile_tokens)
        threshold = self.compaction_threshold
        return TokenBudgetStatus(
            max_context_tokens=self._max_context_tokens,
            current_tokens=total,
            compaction_threshold=threshold,
            compaction_required=total >= threshold,
            usage_ratio=round(total / self._max_context_tokens, 4),
            counter_backend=self._counter.backend,
        )
