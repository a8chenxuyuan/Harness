"""Skill 管理服务 —— 封装 core 层 SkillRepository + SkillTrigger 对外暴露 HTTP 能力。

职责：
    1. 单例管理 SkillRepository（四层聚合仓库，避免重复 load_all）
    2. 把 core 层的 Skill dataclass 转成 API VO（SkillItem）
    3. 注册/注销走运行时层，低层 skill 不影响
    4. 触发测试走 SkillTrigger.match()，仅匹配不激活

不做：
    - 不做 Skill 的持久化（SkillRepository 是内存 + 文件系统）
    - 不做租户隔离（Skill 是全局共享的，注册的 skill 存运行时层）
    - 不做激活（激活由 SkillActivator 在 Agent 运行时触发）
"""

from __future__ import annotations

import logging
from typing import Any

from harness.integrations.skill.model import Skill as CoreSkill
from harness.integrations.skill.repository import (
    LAYER_BUNDLED,
    LAYER_PROJECT,
    LAYER_RUNTIME,
    LAYER_USER,
    SkillRepository,
)
from harness.integrations.skill.trigger import SkillTrigger

log = logging.getLogger(__name__)

# 层标识 → 给前端看的人类可读名称
_LAYER_LABEL = {
    LAYER_RUNTIME: "runtime",   # HTTP API 注册的
    LAYER_USER: "user",         # ~/.harness/skills/
    LAYER_PROJECT: "project",   # {cwd}/.harness/skills/
    LAYER_BUNDLED: "bundled",   # harness 包内置
}

# Service 单例（进程内唯一 SkillRepository，避免重复 load_all）
_repo_instance: SkillRepository | None = None


def get_skill_repository() -> SkillRepository:
    """返回进程内单例 SkillRepository。

    首次调用会延迟实例化；应用启动时可提前显式 init_skill_repository()
    来预热加载，避免第一个请求触发 50ms+ 的磁盘扫描。
    """
    global _repo_instance
    if _repo_instance is None:
        _repo_instance = SkillRepository()
    return _repo_instance


async def init_skill_repository() -> SkillRepository:
    """预热：立即执行 load_all()。应用启动 lifespan 里可选调用。"""
    repo = get_skill_repository()
    if not repo.loaded:
        await repo.load_all()
    return repo


# ---------------------------------------------------------------------------
# Skill dataclass → API VO
# ---------------------------------------------------------------------------

def _skill_to_item(skill: CoreSkill) -> dict[str, Any]:
    """把 core 层 Skill dataclass 转成 SkillItem VO 所需的 dict。

    Skill.metadata 里可能带 ``__layer__`` 内部字段（SkillRepository 用来推断来源层），
    这里取出来作为 ``source`` 字段暴露给前端，然后从 metadata 里剔除以免泄漏内部约定。
    """
    metadata = dict(skill.metadata)
    source = _LAYER_LABEL.get(metadata.pop("__layer__", None), "runtime")
    return {
        "name": skill.name,
        "description": skill.description,
        "version": skill.version,
        "triggers": list(skill.triggers),
        "tools": list(skill.tools),
        "custom_message": skill.custom_message,
        "source": source,
        "metadata": metadata,
    }


# ---------------------------------------------------------------------------
# 五项业务能力
# ---------------------------------------------------------------------------

async def list_skills() -> list[dict[str, Any]]:
    """返回当前全部 Skill，按优先级从高到低排序。"""
    repo = get_skill_repository()
    if not repo.loaded:
        await repo.load_all()
    return [_skill_to_item(s) for s in repo.list_all()]


async def get_skill(name: str) -> dict[str, Any] | None:
    """按名字查 Skill，不存在返回 None。"""
    repo = get_skill_repository()
    if not repo.loaded:
        await repo.load_all()
    skill = repo.get_by_name(name)
    return _skill_to_item(skill) if skill else None


async def register_skill(
    *,
    name: str,
    description: str = "",
    version: str = "1.0.0",
    triggers: list[str] | None = None,
    tools: list[str] | None = None,
    custom_message: str = "",
    metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    """注册一个新 Skill（运行时层）。

    运行时层优先级最高（覆盖 bundled/project/user 同名）。
    同名再注册会替换已有版本。

    Args:
        name: 唯一标识
        description: 简短说明
        version: 语义化版本
        triggers: 触发关键词/正则列表
        tools: 关联工具名列表
        custom_message: 激活时追加的消息正文
        metadata: 扩展字段

    Returns:
        (skill_item_dict, replaced) — replaced=True 表示覆盖了已有同名运行时 Skill
    """
    repo = get_skill_repository()
    if not repo.loaded:
        await repo.load_all()

    # 先查是否已有同名运行时 skill → 用来判断 replaced
    was_runtime = repo.get_by_name(name) is not None

    skill = CoreSkill(
        name=name,
        description=description,
        version=version,
        triggers=list(triggers or []),
        tools=list(tools or []),
        custom_message=custom_message,
        metadata=dict(metadata or {}),
    )
    repo.register(skill)

    log.info("SkillService.register_skill: 注册 %s (replaced=%s)", name, was_runtime)
    return _skill_to_item(skill), was_runtime


async def delete_skill(name: str) -> bool:
    """注销一个运行时 Skill。

    注意：**只从运行时层移除**，不会恢复低层（user/project/bundled）同名 skill。
    如果 Skill 来自低层（不是运行时注册的），删除会失败（返回 False）——
    这是有意的设计：低层 skill 应该通过文件管理，不是 API 删。

    Args:
        name: 要注销的 Skill 名

    Returns:
        True=确实注销了一个运行时 Skill；False=找不到或来自低层
    """
    repo = get_skill_repository()
    if not repo.loaded:
        await repo.load_all()

    existing = repo.get_by_name(name)
    if existing is None:
        return False

    # 判断来源层：只有 runtime 层允许 API 注销
    layer = existing.metadata.get("__layer__") if existing.metadata else None
    if layer != LAYER_RUNTIME:
        log.warning(
            "SkillService.delete_skill: %s 来自 %s 层，API 不允许注销低层 Skill", name, layer
        )
        return False

    removed = repo.unregister(name)
    ok = removed is not None
    if ok:
        log.info("SkillService.delete_skill: 已注销 %s", name)
    return ok


async def trigger_test(text: str) -> list[dict[str, Any]]:
    """测试触发：传一段文本，返回当前加载 Skill 中能命中的列表。

    仅做匹配不做激活，安全无害。
    每个命中项额外返回具体命中的 trigger 字符串（关键词或正则），
    方便前端展示"哪条规则命中了这个 skill"。
    """
    repo = get_skill_repository()
    if not repo.loaded:
        await repo.load_all()

    trigger = SkillTrigger(repo)
    core_matched = await trigger.match(text)

    # 额外算出具体命中的 trigger 字符串（SkillTrigger.match 只返回 Skill，
    # 不告诉你是哪个 trigger 命中的；这里复用 _trigger_matches 逻辑再跑一遍）
    from harness.integrations.skill.trigger import SkillTrigger as _ST

    result: list[dict[str, Any]] = []
    for skill in core_matched:
        matched_trigger = ""
        for t in skill.triggers:
            if _ST._trigger_matches(t, text):
                matched_trigger = t
                break
        result.append({"name": skill.name, "matched_trigger": matched_trigger})

    return result


__all__ = [
    "get_skill_repository",
    "init_skill_repository",
    "list_skills",
    "get_skill",
    "register_skill",
    "delete_skill",
    "trigger_test",
]
