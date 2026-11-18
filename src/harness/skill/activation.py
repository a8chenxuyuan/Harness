"""SkillActivator：把命中的 Skill 追加到 AgentState 的 history。

**核心约束**：只追加到 history，绝对不修改 stable_prefix 的 system_prompt。
原因：
    system_prompt 是 prefix_hash 的组成部分，改了会让全部前缀缓存失效。
    追加到 history 的一条 role="assistant" + custom_message 不影响 hash，
    只有 history 增长。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from harness.message.content_block import TextBlock
from harness.message.msg import Msg
from harness.message.role import Role

from .model import Skill

if TYPE_CHECKING:
    from harness.loop.state import AgentState

log = logging.getLogger(__name__)


class SkillActivator:
    """把 Skill 的 custom_message 追加到 AgentState.messages。

    不修改 system_prompt、不触发 prefix 重建——这是刻意的设计约束。
    """

    # --- 公共入口 --------------------------------------------------------------

    async def activate(self, state: "AgentState", skills: list[Skill]) -> None:
        """激活一组 Skill：每个 skill 在 history 里追加一条 assistant message。

        同一 skill 在一轮里最多激活一次（按 name 去重）。

        Args:
            state: 当前 ReAct 循环状态，messages 会被原地追加。
            skills: 要激活的 Skill 列表。空列表或 custom_message 为空的
                skill 直接跳过。
        """
        if not skills:
            return

        seen: set[str] = set()
        for skill in skills:
            if skill.name in seen:
                continue
            seen.add(skill.name)

            msg_text = skill.custom_message.strip()
            if not msg_text:
                log.debug("SkillActivator: skill %s 无 custom_message，跳过", skill.name)
                continue

            msg = Msg(
                role=Role.ASSISTANT,
                content=[TextBlock(text=msg_text)],
                metadata={"skill": skill.name, "skill_version": skill.version},
            )
            state.messages.append(msg)
            log.info("SkillActivator: 已激活 skill=%s v%s（追加到 history）", skill.name, skill.version)

    # --- 一次性激活所有带自定义 message 的 skill -------------------------------

    async def activate_all(self, state: "AgentState", skills: list[Skill]) -> None:
        """activate 的别名，语义更明确。"""
        await self.activate(state, skills)
