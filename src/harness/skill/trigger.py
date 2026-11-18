"""SkillTrigger：根据用户输入匹配 Skill。

只做匹配，不做激活。激活由 SkillActivator 负责。这样可以让调用者
先拿到候选列表再决定激活策略。
"""

from __future__ import annotations

import logging
import re

from .model import Skill
from .repository import SkillRepository

log = logging.getLogger(__name__)

# 正则 pattern 判定：以 / 开头结尾的字符串
_REGEX_PAT = re.compile(r"^/(.*)/$")


class SkillTrigger:
    """根据触发词 / 正则 pattern 命中 Skill。

    Attributes:
        _repo: 从中取候选 Skill 的仓库。
    """

    def __init__(self, repository: SkillRepository) -> None:
        self._repo = repository

    # --- 公共入口 --------------------------------------------------------------

    async def match(self, text: str) -> list[Skill]:
        """从最新用户输入里匹配所有命中的 Skill。

        Args:
            text: 用户最新输入文本。

        Returns:
            命中的 Skill 列表，按 repo.get_all() 原顺序。无命中返回空列表。
        """
        if not text:
            return []

        candidates = self._repo.get_all()
        matched: list[Skill] = []
        for skill in candidates:
            if self._skill_matches(skill, text):
                matched.append(skill)

        if matched:
            log.debug("SkillTrigger: 命中 %d 个 skill — %s", len(matched), [s.name for s in matched])
        return matched

    # --- 匹配逻辑 --------------------------------------------------------------

    @staticmethod
    def _skill_matches(skill: Skill, text: str) -> bool:
        """判断单个 skill 是否命中用户输入。"""
        for trigger in skill.triggers:
            if SkillTrigger._trigger_matches(trigger, text):
                return True
        return False

    @staticmethod
    def _trigger_matches(trigger: str, text: str) -> bool:
        """判断单个 trigger 是否命中 text。

        trigger 分两种：
            - `/pattern/` → 正则，re.IGNORECASE
            - 其他 → 关键词包含（大小写不敏感）
        """
        if not trigger:
            return False

        regex_match = _REGEX_PAT.match(trigger.strip())
        if regex_match:
            pattern = regex_match.group(1)
            try:
                return re.search(pattern, text, flags=re.IGNORECASE) is not None
            except re.error as exc:
                log.warning("SkillTrigger: 正则无效 %r — %s", trigger, exc)
                return False
        # 普通关键词：大小写不敏感包含
        return trigger.lower() in text.lower()
