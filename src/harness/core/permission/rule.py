"""权限规则数据结构 & 各模式的内置规则集。

PermissionRule 描述一条可匹配工具调用的规则：
匹配成功后返回对应的 action（allow / deny / ask）和 reason。

build_builtin_rules 为每种 PermissionMode 生成一份默认规则列表，
PermissionEngine 会先扫描自定义规则，再按顺序匹配内置规则。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .mode import PermissionMode

RuleAction = Literal["allow", "deny", "ask"]


@dataclass(frozen=True)
class PermissionRule:
    """一条权限规则。

    Attributes:
        id: 规则唯一标识，便于日志追踪与覆盖。
        tool_name: 目标工具名；None 表示通配所有工具。
        condition: 可选的 eval 表达式字符串，eval 时注入 args dict
            作为局部变量；例如 ``"args.get('path','').startswith('/etc')"``。
            省略时视为无条件命中。
        action: 命中后的决策——allow / deny / ask。
        reason: 命中后返回给上层的说明文字。
    """

    id: str
    tool_name: str | None
    condition: str | None
    action: RuleAction
    reason: str


# ---------------------------------------------------------------------------
# 内置规则生成
# ---------------------------------------------------------------------------

# 判定"是否写工具"的启发式：已知只读工具名单。
_READONLY_TOOLS = {"read_file", "search_file", "grep", "bash_readonly", "http_get"}

# 低风险写工具（AGENTIC 模式下可直接放行）
_LOW_RISK_WRITE_TOOLS = {"create_file", "mkdir", "write_file"}

# 高风险命令片段（bash command 包含即视为危险）
_HIGH_RISK_CMD_PATTERNS = [
    "rm -rf /",
    "rm -rf /*",
    "shutdown",
    "reboot",
    "init 0",
    "mkfs",
    "dd if=/dev/zero",
]


def _high_risk_bash_condition() -> str:
    """生成一个 condition 表达式，命中 bash 高风险命令。"""
    checks = " or ".join(
        f"'{pat}' in args.get('command', '')" for pat in _HIGH_RISK_CMD_PATTERNS
    )
    return checks


def _is_readonly_tool_condition() -> str:
    """命中所有 readonly 工具的通用 condition。"""
    readonly_set = ", ".join(f"'{t}'" for t in sorted(_READONLY_TOOLS))
    return f"tool_name in {{{readonly_set}}}"


def _is_write_tool_condition() -> str:
    """命中所有非 readonly 工具的通用 condition。"""
    readonly_set = ", ".join(f"'{t}'" for t in sorted(_READONLY_TOOLS))
    return (
        f"tool_name not in {{{readonly_set}}} "
        "and tool_name is not None"
    )


def build_builtin_rules(mode: PermissionMode) -> list[PermissionRule]:
    """为给定模式生成一份内置规则列表。

    Args:
        mode: 权限模式。

    Returns:
        按优先级排序的 PermissionRule 列表（先匹配先生效）。
    """
    rules: list[PermissionRule] = []

    if mode == PermissionMode.TRUSTED:
        rules.append(
            PermissionRule(
                id="trusted_all_allow",
                tool_name=None,
                condition=None,
                action="allow",
                reason="trusted mode: all tools allowed",
            )
        )
        return rules

    if mode == PermissionMode.LOCKDOWN:
        rules.append(
            PermissionRule(
                id="lockdown_all_deny",
                tool_name=None,
                condition=None,
                action="deny",
                reason="lockdown mode: all tools denied",
            )
        )
        return rules

    # EXPLORE / DEFAULT / AGENTIC 共有：高风险 bash 一律 DENY
    rules.append(
        PermissionRule(
            id="hard_deny_high_risk_bash",
            tool_name="bash",
            condition=_high_risk_bash_condition(),
            action="deny",
            reason="high-risk bash command denied by built-in rule",
        )
    )

    # 只读工具在三种模式下一律 ALLOW（必须排在 deny/ask 写规则之前）
    rules.append(
        PermissionRule(
            id="allow_readonly_tools",
            tool_name=None,
            condition=_is_readonly_tool_condition(),
            action="allow",
            reason="readonly tool allowed by built-in rule",
        )
    )

    if mode == PermissionMode.EXPLORE:
        # 所有非 readonly 工具 → DENY
        rules.append(
            PermissionRule(
                id="explore_deny_all_write",
                tool_name=None,
                condition=_is_write_tool_condition(),
                action="deny",
                reason="explore mode: write tools denied",
            )
        )
        return rules

    if mode == PermissionMode.DEFAULT:
        # 所有写工具 → ASK
        rules.append(
            PermissionRule(
                id="default_ask_all_write",
                tool_name=None,
                condition=_is_write_tool_condition(),
                action="ask",
                reason="default mode: write tool requires HITL approval",
            )
        )
        return rules

    if mode == PermissionMode.AGENTIC:
        # 低风险写工具 → ALLOW
        for tname in sorted(_LOW_RISK_WRITE_TOOLS):
            rules.append(
                PermissionRule(
                    id=f"agentic_allow_{tname}",
                    tool_name=tname,
                    condition=None,
                    action="allow",
                    reason=f"agentic mode: low-risk write tool {tname} allowed",
                )
            )
        # 其余写 → ASK
        rules.append(
            PermissionRule(
                id="agentic_ask_rest_write",
                tool_name=None,
                condition=_is_write_tool_condition(),
                action="ask",
                reason="agentic mode: write tool requires HITL approval",
            )
        )
        return rules

    # 理论不可达，兜底返回空
    return rules
