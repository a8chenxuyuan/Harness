"""Skill 系统（Phase 13）。

对外导出：
    * Skill — 数据模型
    * SkillLoader — 从磁盘加载 SKILL.md
    * SkillRepository — 四层聚合仓库
    * SkillTrigger — 关键词 / 正则匹配
    * SkillActivator — 追加 custom_message 到 history
"""

from .activation import SkillActivator
from .loader import SkillLoader
from .model import Skill
from .repository import SkillRepository
from .trigger import SkillTrigger

__all__ = [
    "Skill",
    "SkillActivator",
    "SkillLoader",
    "SkillRepository",
    "SkillTrigger",
]
