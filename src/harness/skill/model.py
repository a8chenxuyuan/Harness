"""Skill 数据模型。

Skill 是一段可被激活的"技能包"：命中触发词时，它的 custom_message
会被追加到会话历史中，让模型以一种新的"人格"或"专家"视角继续推理。

**关键约束**：Skill 绝不修改 stable_prefix 的 system_prompt，只追加
到 history。这样 prefix_hash 不变，缓存不失效。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Skill:
    """一个可被 SkillTrigger 命中、由 SkillActivator 激活的技能定义。

    Attributes:
        name: 唯一标识，用于 repository 层去重和运行时注册。
        description: 给 LLM / 调试用的简短说明。
        version: 语义化版本号，默认 1.0.0。
        triggers: 触发关键词或正则 pattern（以 /.../ 包裹）。
        tools: Skill 自带的工具名列表，激活时可通知 ToolRegistry 注册。
        system_prompt: **废弃字段**，保留兼容但不再使用；改它会让
            stable_prefix 失效。新版统一用 custom_message 追加到 history。
        custom_message: 激活时追加到 history 的特殊消息正文。
        metadata: 任意扩展字段（作者、来源、标签等）。
    """

    name: str
    description: str = ""
    version: str = "1.0.0"
    triggers: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    system_prompt: str = ""  # deprecated, kept for backward compat
    custom_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    # --- 工具方法 ---------------------------------------------------------------

    def with_triggers(self, extra: list[str]) -> "Skill":
        """返回一个 triggers 合并后的新实例（frozen 不可变，必须重建）。"""
        return Skill(
            name=self.name,
            description=self.description,
            version=self.version,
            triggers=[*self.triggers, *extra],
            tools=self.tools,
            custom_message=self.custom_message,
            metadata=self.metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """导出字典，便于序列化和日志打印。"""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "triggers": list(self.triggers),
            "tools": list(self.tools),
            "custom_message": self.custom_message,
            "metadata": dict(self.metadata),
        }

    def __repr__(self) -> str:  # pragma: no cover - 调试友好
        return f"<Skill name={self.name!r} v{self.version} triggers={len(self.triggers)}>"
