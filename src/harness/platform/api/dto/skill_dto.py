"""Skill 管理接口入参（DTO）。

所有请求模型；响应模型在 ``api.vo.skill_vo``。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SkillRegisterRequest(BaseModel):
    """POST /skills 请求体 —— 注册一个新 Skill（运行时层）。

    Skill 的 custom_message 会在命中触发词时追加到会话 history，
    让模型以新的专家视角继续推理。**不会修改 stable_prefix**，
    确保前缀缓存不失效。
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="唯一标识，注册后不可改。同名会覆盖运行时层已有版本",
    )
    description: str = Field(default="", max_length=500, description="给 LLM 和调试用的简短说明")
    version: str = Field(default="1.0.0", max_length=32, description="语义化版本号")
    triggers: list[str] = Field(
        default_factory=list,
        max_length=50,
        description="触发关键词或 /regex/ 正则 pattern；大小写不敏感",
    )
    tools: list[str] = Field(
        default_factory=list,
        max_length=50,
        description="Skill 自带的工具名列表（激活时通知 ToolRegistry 注册）",
    )
    custom_message: str = Field(
        default="",
        description="命中后追加到 history 的特殊消息正文（人格/专家视角定义）",
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展字段（作者、标签等）")


class SkillPatchRequest(BaseModel):
    """PATCH /skills/{name} 请求体 —— 启用/禁用一个 Skill。

    只支持 enabled 一个字段；禁用后 SkillTrigger 不再命中，
    重新启用立即恢复，无需重新注册。
    """

    enabled: bool = Field(..., description="True=启用，False=禁用")


class SkillTriggerTestRequest(BaseModel):
    """POST /skills/trigger-test 请求体 —— 测试 Skill 匹配效果。

    传一段文本，返回当前已加载 Skill 中能命中的列表。
    仅做匹配不做激活，安全无害。
    """

    text: str = Field(..., min_length=1, max_length=4000, description="要测试的输入文本")


__all__ = ["SkillRegisterRequest", "SkillPatchRequest", "SkillTriggerTestRequest"]
