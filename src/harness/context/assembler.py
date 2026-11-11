        """上下文装配器：每次调模型前装配请求体的唯一入口。

唯一职责：把「系统提示 + 工具定义」压成会话内字节不变的稳定前缀，
再把「历史 + 本轮临时上下文」按层附上，同时给出缓存提示与 token 预算结论。

职责边界：
    不调模型、不做压缩、不写会话存储。压缩信号只通过 token_budget 传给上层。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..message.canonical import canonical_bytes, canonical_json, sorted_deep
from ..message.msg import Msg
from .cache_policy import (
    CacheHints,
    CacheProfile,
    build_cache_hints,
    profile_for,
)
from .prefix_guard import PrefixChangeReason, PrefixCheckResult, PrefixGuard
from .token_budget import TokenBudget, TokenBudgetStatus


class StablePrefix(BaseModel):
    """会话内字节不变的部分。

    Attributes:
        system_prompt: 系统提示正文。
        tool_schemas: 工具定义，已按名称稳定排序。
        prefix_hash: 上述内容的 sha256，用于断言两轮前缀一致。
        prefix_tokens: 稳定前缀的 token 数。
    """

    model_config = ConfigDict(extra="forbid")

    system_prompt: str
    tool_schemas: list[dict[str, Any]]
    prefix_hash: str
    prefix_tokens: int


class AssembledContext(BaseModel):
    """一次装配的完整结果，等价于设计文档中的装配结果 JSON。

    Attributes:
        session_id: 会话标识。
        stable_prefix: 稳定前缀。
        history: 只追加的历史消息。
        volatile_context: 本轮临时信息，不进缓存前缀。
        cache_hints: 供应商缓存断点。
        token_budget: 预算结论与压缩信号。
        prefix_check: 前缀稳定性检查结论。
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    stable_prefix: StablePrefix
    history: list[Msg] = Field(default_factory=list)
    volatile_context: dict[str, Any] = Field(default_factory=dict)
    cache_hints: CacheHints
    token_budget: TokenBudgetStatus
    prefix_check: PrefixCheckResult

    def to_dict(self) -> dict[str, Any]:
        """导出装配结果字典，字段顺序与设计文档一致，便于日志对照。

        Returns:
            可直接打印或落盘的字典。
        """
        return {
            "session_id": self.session_id,
            "stable_prefix": {
                "system_prompt": self.stable_prefix.system_prompt,
                "tool_schemas": self.stable_prefix.tool_schemas,
                "prefix_hash": self.stable_prefix.prefix_hash,
                "prefix_tokens": self.stable_prefix.prefix_tokens,
            },
            "history": [message.to_dict() for message in self.history],
            "volatile_context": sorted_deep(self.volatile_context),
            "cache_hints": {
                "provider": self.cache_hints.provider,
                "mode": self.cache_hints.mode.value,
                "breakpoints": [
                    {"after": point.after, "ttl": point.ttl}
                    for point in self.cache_hints.breakpoints
                ],
                "prompt_cache_key": self.cache_hints.prompt_cache_key,
                "prefix_cacheable": self.cache_hints.prefix_cacheable,
            },
            "token_budget": self.token_budget.model_dump(),
        }


class ContextAssembler:
    """上下文装配器。

    唯一职责：装配请求分层并保持稳定前缀字节不变。
    稳定前缀在构造时定型，之后每轮只追加历史与临时上下文。
    """

    def __init__(
        self,
        system_prompt: str,
        tool_schemas: Sequence[Mapping[str, Any]] = (),
        profile: CacheProfile | None = None,
        max_context_tokens: int = 32_000,
        compaction_ratio: float = 0.8,
        guard: PrefixGuard | None = None,
        budget: TokenBudget | None = None,
    ) -> None:
        """构造装配器并立即定型稳定前缀。

        Args:
            system_prompt: 系统提示正文；会话开始后不应再改动。
            tool_schemas: 工具定义列表，构造时会按名称排序。
            profile: 供应商缓存画像，缺省按 DeepSeek 的自动缓存处理。
            max_context_tokens: 上下文窗口上限。
            compaction_ratio: 触发压缩的比例。
            guard: 前缀守卫，缺省新建严格守卫。
            budget: 预算器，缺省按窗口上限新建。

        Raises:
            PrefixStabilityError: 系统提示或工具定义里含时间戳、UUID 等易变内容。
        """
        self._profile = profile or profile_for("deepseek")
        self._guard = guard or PrefixGuard()
        self._budget = budget or TokenBudget(
            max_context_tokens=max_context_tokens,
            compaction_ratio=compaction_ratio,
        )
        self._system_prompt = system_prompt
        self._tool_schemas = self._normalize_tool_schemas(tool_schemas)

        payload = {"system_prompt": system_prompt, "tool_schemas": self._tool_schemas}
        prefix_bytes = canonical_bytes(payload)
        self._guard.assert_stable_content(prefix_bytes.decode("utf-8"))
        self._prefix_hash = "sha256:" + hashlib.sha256(prefix_bytes).hexdigest()
        self._prefix_tokens = self._budget.counter.count(prefix_bytes.decode("utf-8"))

    @staticmethod
    def _normalize_tool_schemas(
        tool_schemas: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """把工具定义规范化成稳定顺序与稳定键序。

        Args:
            tool_schemas: 原始工具定义。

        Returns:
            按名称排序、内部键名递归排序后的工具定义列表。
        """
        normalized = [sorted_deep(dict(schema)) for schema in tool_schemas]
        return sorted(
            normalized,
            key=lambda schema: (str(schema.get("name", "")), canonical_json(schema)),
        )

    @property
    def prefix_hash(self) -> str:
        """稳定前缀哈希，形如 `sha256:<hex>`。"""
        return self._prefix_hash

    @property
    def prefix_tokens(self) -> int:
        """稳定前缀的 token 数。"""
        return self._prefix_tokens

    @property
    def profile(self) -> CacheProfile:
        """当前使用的供应商缓存画像。"""
        return self._profile

    @property
    def guard(self) -> PrefixGuard:
        """当前使用的前缀守卫。"""
        return self._guard

    def assemble(
        self,
        history: Sequence[Msg],
        volatile_context: Mapping[str, Any] | None = None,
        session_id: str = "default",
        reason: PrefixChangeReason | None = None,
    ) -> AssembledContext:
        """装配一轮请求。

        Args:
            history: 只追加的历史消息，调用方负责顺序。
            volatile_context: 本轮临时信息（当前时间、临时插话），不进稳定前缀。
            session_id: 会话标识，用于缓存键与前缀守卫记账。
            reason: 本次装配声明的前缀变化理由，通常为 None。

        Returns:
            含稳定前缀、历史、临时上下文、缓存提示与预算结论的装配结果。

        Raises:
            PrefixStabilityError: 前缀被非白名单理由改变。
        """
        volatile = dict(volatile_context or {})
        history_list = list(history)

        history_tokens = self._budget.counter.count_messages(history_list)
        volatile_tokens = (
            self._budget.counter.count(canonical_json(sorted_deep(volatile))) if volatile else 0
        )
        status = self._budget.evaluate(self._prefix_tokens, history_tokens, volatile_tokens)
        check = self._guard.check(session_id, self._prefix_hash, reason)
        hints = build_cache_hints(
            profile=self._profile,
            prefix_tokens=self._prefix_tokens,
            session_id=session_id,
            history_length=len(history_list),
        )

        return AssembledContext(
            session_id=session_id,
            stable_prefix=StablePrefix(
                system_prompt=self._system_prompt,
                tool_schemas=self._tool_schemas,
                prefix_hash=self._prefix_hash,
                prefix_tokens=self._prefix_tokens,
            ),
            history=history_list,
            volatile_context=volatile,
            cache_hints=hints,
            token_budget=status,
            prefix_check=check,
        )
