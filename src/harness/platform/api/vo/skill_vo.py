"""Skill 管理接口出参（VO）。

请求模型在 ``api.dto.skill_dto``。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SkillItem(BaseModel):
    """单个 Skill 的展示项（列表/详情共用）。"""

    name: str = Field(..., description="唯一标识")
    description: str = Field(default="", description="简短说明")
    version: str = Field(default="1.0.0", description="语义化版本")
    triggers: list[str] = Field(default_factory=list, description="触发关键词/正则")
    tools: list[str] = Field(default_factory=list, description="关联工具")
    custom_message: str = Field(default="", description="激活时追加的特殊消息正文")
    enabled: bool = Field(default=True, description="是否启用；禁用后 SkillTrigger 不再命中")
    source: str = Field(
        default="runtime",
        description="来源层：runtime / user / project / bundled（四层聚合仓库的优先级标识）",
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展字段")


class SkillListResponse(BaseModel):
    """GET /skills 响应体 —— Skill 列表 + 总数。"""

    items: list[SkillItem] = Field(default_factory=list, description="Skill 项列表，按优先级从高到低排序")
    total: int = Field(default=0, description="总数")


class SkillDetailResponse(BaseModel):
    """GET /skills/{name} 响应体 —— 单个 Skill 详情。"""

    skill: SkillItem | None = Field(default=None, description="命中的 Skill；不存在返回 null")


class SkillTriggerMatch(BaseModel):
    """POST /skills/trigger-test 响应中单个命中项。"""

    name: str = Field(..., description="命中的 Skill 名")
    matched_trigger: str = Field(..., description="具体命中的 trigger（关键词或正则 pattern）")


class SkillTriggerTestResponse(BaseModel):
    """POST /skills/trigger-test 响应体 —— 触发测试结果。"""

    matched: list[SkillTriggerMatch] = Field(default_factory=list, description="命中的 Skill 列表")
    total_matches: int = Field(default=0, description="命中总数")


class SkillRegisterResponse(BaseModel):
    """POST /skills 响应体 —— 注册完成后的 Skill 快照。"""

    skill: SkillItem = Field(..., description="新注册的 Skill 项")
    replaced: bool = Field(default=False, description="是否覆盖了同名运行时 Skill（true=已有同名被替换）")


class SkillDeleteResponse(BaseModel):
    """DELETE /skills/{name} 响应体 —— 注销结果。"""

    deleted: bool = Field(default=True, description="true=确实注销了一个运行时 Skill；false=找不到或来自低层（低层不删）")


class SkillPatchResponse(BaseModel):
    """PATCH /skills/{name} 响应体 —— 启用/禁用后的 Skill 快照。"""

    skill: SkillItem = Field(..., description="更新后的 Skill 项")


class SkillVersionItem(BaseModel):
    """GET /skills/{name}/versions 响应中的单个历史版本。"""

    version: str = Field(..., description="旧版本的语义化版本号")
    description: str = Field(default="", description="旧版本的简短说明")
    source: str = Field(default="runtime", description="旧版本的来源层")
    replaced_at: str = Field(..., description="被覆盖的时间（UTC ISO 字符串）")


class SkillVersionsResponse(BaseModel):
    """GET /skills/{name}/versions 响应体 —— 内存版历史版本列表。"""

    items: list[SkillVersionItem] = Field(default_factory=list, description="历史版本，新版本在前")
    total: int = Field(default=0, description="历史版本数")


__all__ = [
    "SkillItem",
    "SkillListResponse",
    "SkillDetailResponse",
    "SkillTriggerMatch",
    "SkillTriggerTestResponse",
    "SkillRegisterResponse",
    "SkillDeleteResponse",
    "SkillPatchResponse",
    "SkillVersionItem",
    "SkillVersionsResponse",
]
