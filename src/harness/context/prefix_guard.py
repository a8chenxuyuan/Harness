"""前缀稳定性守卫。

唯一职责：保证「会话内稳定前缀的字节不变」，变了就必须给出白名单里的理由。

两道检查：
    1. 内容检查：稳定前缀里出现时间戳、UUID 这类易变值时立刻抛错。
    2. 哈希检查：本轮 prefix_hash 与上一轮不同、且理由不在白名单时抛错。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import Enum

from pydantic import BaseModel, ConfigDict


class PrefixChangeReason(str, Enum):
    """允许改变稳定前缀的合法理由。

    Attributes:
        SESSION_START: 新会话，还没有历史前缀。
        TOOLSET_CHANGED: 工具集变化（如接入 MCP），需要提示开新会话。
        COMPACTION_APPLIED: 压缩后重建窗口，一次性变化。
        MODEL_SWITCHED: 换模型，缓存本来就按模型隔离。
        CONFIG_RELOADED: 系统提示被显式重载。
    """

    SESSION_START = "session_start"
    TOOLSET_CHANGED = "toolset_changed"
    COMPACTION_APPLIED = "compaction_applied"
    MODEL_SWITCHED = "model_switched"
    CONFIG_RELOADED = "config_reloaded"


class PrefixStabilityError(RuntimeError):
    """稳定前缀被破坏时抛出。"""


class PrefixCheckResult(BaseModel):
    """一次前缀检查的结论。

    Attributes:
        session_id: 会话标识。
        prefix_hash: 本轮前缀哈希。
        changed: 与上一轮相比是否变化。
        reason: 变化理由；未变化时为 None。
        stable_rounds: 前缀连续未变化的轮数（含本轮）。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    prefix_hash: str
    changed: bool
    reason: PrefixChangeReason | None = None
    stable_rounds: int = 0


_VOLATILE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"), "ISO-8601 时间戳"),
    (
        re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"),
        "UUID",
    ),
)
"""禁止出现在稳定前缀中的易变内容。每命中一条，都会让该点之后的缓存失效。"""


class PrefixGuard:
    """前缀守卫。

    按会话记录上一轮的 prefix_hash 与连续稳定轮数，变化必须命中白名单理由。
    """

    def __init__(self, strict: bool = True, allowed_reasons: Iterable[str] = ()) -> None:
        """初始化守卫。

        Args:
            strict: 为 True 时违规直接抛错；为 False 时只记录结论不抛错。
            allowed_reasons: 额外的白名单理由（如接入第三方后的自定义原因）。
        """
        self._strict = strict
        self._allowed = {reason.value for reason in PrefixChangeReason}
        self._allowed.update(allowed_reasons)
        self._hashes: dict[str, str] = {}
        self._stable_rounds: dict[str, int] = {}

    @property
    def strict(self) -> bool:
        """是否处于严格模式。"""
        return self._strict

    def check(
        self,
        session_id: str,
        prefix_hash: str,
        reason: PrefixChangeReason | None = None,
    ) -> PrefixCheckResult:
        """比对并记录本轮前缀哈希。

        Args:
            session_id: 会话标识。
            prefix_hash: 本轮装配出的前缀哈希。
            reason: 调用方声明的前缀变化理由。

        Returns:
            本次检查的结论。

        Raises:
            PrefixStabilityError: 严格模式下前缀变了但理由不在白名单内。
        """
        previous = self._hashes.get(session_id)
        if previous is None:
            self._hashes[session_id] = prefix_hash
            self._stable_rounds[session_id] = 1
            return PrefixCheckResult(
                session_id=session_id,
                prefix_hash=prefix_hash,
                changed=True,
                reason=reason or PrefixChangeReason.SESSION_START,
                stable_rounds=1,
            )

        if previous == prefix_hash:
            rounds = self._stable_rounds.get(session_id, 1) + 1
            self._stable_rounds[session_id] = rounds
            return PrefixCheckResult(
                session_id=session_id,
                prefix_hash=prefix_hash,
                changed=False,
                stable_rounds=rounds,
            )

        if reason is None or reason.value not in self._allowed:
            message = (
                f"会话 {session_id} 的稳定前缀发生变化且未命中白名单理由："
                f"{previous} -> {prefix_hash}"
            )
            if self._strict:
                raise PrefixStabilityError(message)
            self._hashes[session_id] = prefix_hash
            self._stable_rounds[session_id] = 1
            return PrefixCheckResult(
                session_id=session_id,
                prefix_hash=prefix_hash,
                changed=True,
                stable_rounds=1,
            )

        self._hashes[session_id] = prefix_hash
        self._stable_rounds[session_id] = 1
        return PrefixCheckResult(
            session_id=session_id,
            prefix_hash=prefix_hash,
            changed=True,
            reason=reason,
            stable_rounds=1,
        )

    def assert_stable_content(self, text: str, where: str = "stable_prefix") -> None:
        """检查文本里是否混入了易变内容。

        Args:
            text: 待检查的稳定前缀文本（通常是规范 JSON）。
            where: 出错信息里的位置描述。

        Raises:
            PrefixStabilityError: 命中时间戳或 UUID 等易变模式。
        """
        for pattern, label in _VOLATILE_PATTERNS:
            matched = pattern.search(text)
            if matched is not None:
                raise PrefixStabilityError(
                    f"{where} 中出现{label}（{matched.group(0)}）；"
                    "这类内容每轮都会变，会让该点之后的缓存全部失效"
                )

    def reset(self, session_id: str) -> None:
        """清空某个会话的记录，用于压缩或主动重建窗口后重新计数。

        Args:
            session_id: 会话标识。
        """
        self._hashes.pop(session_id, None)
        self._stable_rounds.pop(session_id, None)

    def known_hash(self, session_id: str) -> str | None:
        """返回会话上一轮的哈希，便于日志对照。

        Args:
            session_id: 会话标识。

        Returns:
            上一轮哈希；从未装配过时为 None。
        """
        return self._hashes.get(session_id)
