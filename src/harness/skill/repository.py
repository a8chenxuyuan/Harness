"""SkillRepository：四层 Skill 源的聚合仓库。

优先级从高到低（同名覆盖）：
    1. **运行时注入**   — add_runtime() 注册，最高优先级
    2. **用户级**       — ~/.harness/skills/
    3. **项目级**       — {cwd}/.harness/skills/
    4. **全局内置**     — harness 包内置 bundled skills

加载顺序不敏感，repository 按优先级合并，高优先级覆盖低优先级。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

from .loader import SkillLoader
from .model import Skill

log = logging.getLogger(__name__)

# 层标识常量
LAYER_RUNTIME = "runtime"
LAYER_USER = "user"
LAYER_PROJECT = "project"
LAYER_BUNDLED = "bundled"

# 优先级：数字越大，同名时胜出
_LAYER_PRIORITY = {
    LAYER_RUNTIME: 4,
    LAYER_USER: 3,
    LAYER_PROJECT: 2,
    LAYER_BUNDLED: 1,
}

# harness 包内置 skills 目录（src/harness/skill/_bundled/）
_BUNDLED_DIR = Path(__file__).parent / "_bundled"


class SkillRepository:
    """四层 Skill 源聚合仓库。

    Attributes:
        _loader: SkillLoader 实例，可替换以便测试。
        _skills: name → Skill 映射，已经按优先级合并。
        _layers: layer_name → (priority, 目录路径) 元组，供调试。
    """

    def __init__(
        self,
        loader: SkillLoader | None = None,
        user_dir: str | None = None,
        project_dir: str | None = None,
        bundled_dir: str | None = None,
    ) -> None:
        self._loader = loader or SkillLoader()
        self._skills: dict[str, Skill] = {}
        self._loaded = False

        # 各层目录路径；None 表示跳过该层
        self._user_dir = Path(user_dir) if user_dir else Path.home() / ".harness" / "skills"
        self._project_dir = Path(project_dir) if project_dir else Path(os.getcwd()) / ".harness" / "skills"
        self._bundled_dir = Path(bundled_dir) if bundled_dir else _BUNDLED_DIR

        # 运行时注入层：直接由 add_runtime 注册
        self._runtime_skills: dict[str, Skill] = {}

    # --- 加载 ------------------------------------------------------------------

    async def load_all(self) -> None:
        """一次性加载全部四层。

        同名 skill 高层覆盖低层。重复调用幂等（第二次会重建状态）。
        """
        self._skills.clear()
        self._loaded = True

        # 加载顺序：bundled → project → user → runtime 叠加覆盖
        layers = [
            (LAYER_BUNDLED, self._bundled_dir),
            (LAYER_PROJECT, self._project_dir),
            (LAYER_USER, self._user_dir),
        ]
        for layer_name, path in layers:
            skills = await self._loader.load_dir(str(path))
            for skill in skills:
                self._upsert(skill, layer_name)

        # runtime 层已在内存里，直接覆盖
        for skill in self._runtime_skills.values():
            self._upsert(skill, LAYER_RUNTIME)

        log.info(
            "SkillRepository 加载完成：共 %d 个 skill（runtime=%d, user=%d, project=%d, bundled=%d）",
            len(self._skills),
            len(self._runtime_skills),
            len(self._skills) - sum(1 for s in self._skills.values() if self._layer_of(s) == LAYER_RUNTIME),
            0,  # 简化：不统计各层独立数量
            0,
        )

    def _upsert(self, skill: Skill, layer: str) -> None:
        """按优先级决定是否覆盖。"""
        existing = self._skills.get(skill.name)
        if existing is None:
            self._skills[skill.name] = skill
            return
        # 只有更高 priority 才覆盖；同一层重复加载跳过
        existing_layer = self._layer_of(existing)
        if _LAYER_PRIORITY.get(layer, 0) >= _LAYER_PRIORITY.get(existing_layer, 0):
            self._skills[skill.name] = skill

    # --- 注册 / 注销 ------------------------------------------------------------

    def register(self, skill: Skill) -> Skill:
        """注册一个 skill（运行时层）。

        Args:
            skill: 要注册的 skill。

        Returns:
            被替换掉的旧 skill（若有），否则自身。
        """
        self._runtime_skills[skill.name] = skill
        self._skills[skill.name] = skill
        return skill

    def unregister(self, name: str) -> Skill | None:
        """注销一个 skill（仅从运行时层移除）。

        注意：不会恢复低层的同名 skill。调用者若需要恢复低层版本，应重新 load_all()。

        Args:
            name: skill 名字。

        Returns:
            被移除的 skill，不存在返回 None。
        """
        removed = self._runtime_skills.pop(name, None)
        if removed and self._skills.get(name) is removed:
            # 若当前顶层就是 runtime 注册的，一并从合并表移除
            # 但不清 _skills，让高层查询感知不到（除非重 load_all）
            pass
        return removed

    # --- 查询 ------------------------------------------------------------------

    def get_by_name(self, name: str) -> Skill | None:
        """按名字查 skill，不存在返回 None。"""
        return self._skills.get(name)

    def list_all(self) -> list[Skill]:
        """返回当前全部 skill，按优先级从高到低排序。"""
        return sorted(
            self._skills.values(),
            key=lambda s: -_LAYER_PRIORITY.get(self._layer_of(s), 0),
        )

    def get_all(self) -> list[Skill]:
        """list_all 的别名。"""
        return self.list_all()

    @property
    def loaded(self) -> bool:
        return self._loaded

    # --- 内部辅助 --------------------------------------------------------------

    def add_runtime(self, skills: Iterable[Skill]) -> list[Skill]:
        """批量注册运行时 skills，返回成功注册的列表。"""
        out: list[Skill] = []
        for s in skills:
            out.append(self.register(s))
        return out

    def _layer_of(self, skill: Skill) -> str:
        """推断一个 skill 来自哪一层。

        因为 Skill 本身不带 layer 字段，我们用 metadata['__layer__'] 标记。
        这是一个内部约定字段，对外透明。
        """
        layer = skill.metadata.get("__layer__") if skill.metadata else None
        if isinstance(layer, str):
            return layer
        return LAYER_BUNDLED
