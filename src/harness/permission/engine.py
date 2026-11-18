"""权限决策引擎。

PermissionEngine 组合 PermissionMode 的内置规则与用户自定义规则，
对每次工具调用产出 PermissionDecision。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from .mode import PermissionMode
from .rule import PermissionRule, build_builtin_rules

log = logging.getLogger(__name__)

Decision = Literal["allow", "deny", "ask"]


@dataclass(frozen=True)
class PermissionDecision:
    """一次权限评估的结果。

    Attributes:
        decision: allow / deny / ask。
        reason: 决策说明，便于日志和 HITL 提示。
        rule_id: 命中的规则 id；无命中则为 None。
    """

    decision: Decision
    reason: str
    rule_id: str | None


class PermissionEngine:
    """权限决策引擎——为每次工具调用挑选一条规则并产出 PermissionDecision。

    扫描顺序：
        1. custom_rules（后加入者优先级更高）
        2. 当前 mode 的内置规则（按 build_builtin_rules 返回顺序）
        3. 兜底默认（mode 决定默认值）

    Attributes:
        mode: 当前权限模式。
        custom_rules: 用户追加的自定义规则列表。
    """

    _DEFAULT_BY_MODE: dict[PermissionMode, Decision] = {
        PermissionMode.EXPLORE: "deny",
        PermissionMode.DEFAULT: "ask",
        PermissionMode.AGENTIC: "ask",
        PermissionMode.TRUSTED: "allow",
        PermissionMode.LOCKDOWN: "deny",
    }

    def __init__(
        self,
        mode: PermissionMode,
        custom_rules: list[PermissionRule] | None = None,
    ) -> None:
        """初始化引擎。

        Args:
            mode: 权限模式。
            custom_rules: 初始自定义规则列表；后续可通过 add_rule 追加。
        """
        self.mode: PermissionMode = mode
        self.custom_rules: list[PermissionRule] = list(custom_rules or [])
        self._builtin_rules: list[PermissionRule] = build_builtin_rules(mode)

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def add_rule(self, rule: PermissionRule) -> None:
        """追加一条自定义规则，优先级高于内置规则。

        Args:
            rule: 新规则。
        """
        self.custom_rules.append(rule)

    def set_mode(self, mode: PermissionMode) -> None:
        """切换权限模式（会重新构建内置规则）。

        Args:
            mode: 新模式。
        """
        self.mode = mode
        self._builtin_rules = build_builtin_rules(mode)

    async def evaluate(self, tool_name: str, args: dict) -> PermissionDecision:
        """评估一次工具调用，产出决策。

        Args:
            tool_name: 被调用的工具名。
            args: 工具调用参数。

        Returns:
            PermissionDecision 实例。
        """
        # 1. 自定义规则（后加入先扫，让调用者可覆盖早先添加的规则）
        for rule in reversed(self.custom_rules):
            if self._match(rule, tool_name, args):
                log.debug("custom rule hit: %s -> %s", rule.id, rule.action)
                return PermissionDecision(
                    decision=rule.action, reason=rule.reason, rule_id=rule.id
                )

        # 2. 内置规则（顺序匹配）
        for rule in self._builtin_rules:
            if self._match(rule, tool_name, args):
                log.debug("builtin rule hit: %s -> %s", rule.id, rule.action)
                return PermissionDecision(
                    decision=rule.action, reason=rule.reason, rule_id=rule.id
                )

        # 3. 兜底默认
        default_action = self._DEFAULT_BY_MODE[self.mode]
        log.debug("no rule hit, fallback default for mode=%s -> %s", self.mode, default_action)
        return PermissionDecision(
            decision=default_action,
            reason=f"default decision for mode={self.mode.value}",
            rule_id=None,
        )

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _match(rule: PermissionRule, tool_name: str, args: dict) -> bool:
        """判断规则是否命中。

        - tool_name 为 None 时通配；否则需精确匹配。
        - condition 为 None 时无条件；否则用受限 builtins 执行 eval。

        Args:
            rule: 待匹配规则。
            tool_name: 当前工具名。
            args: 工具参数。

        Returns:
            是否命中。
        """
        if rule.tool_name is not None and rule.tool_name != tool_name:
            return False
        if rule.condition is None:
            return True
        # 受限 builtins，防止 eval 注入；同时注入 args 与展开后的字段
        sandbox: dict = {"__builtins__": {}, "tool_name": tool_name, "args": args}
        sandbox.update(args)
        try:
            return bool(eval(rule.condition, sandbox))
        except Exception as exc:  # noqa: BLE001 - 条件表达式异常不影响主流程
            log.warning("condition eval failed for rule %s: %s", rule.id, exc)
            return False
