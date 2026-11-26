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
from datetime import UTC, datetime
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

# 版本历史（内存态）：name → 旧版本快照列表，新版本在前。
# register_skill 覆盖同名 Skill 时，把被替换的旧版本记录到这里，
# 供 GET /skills/{name}/versions 查询。进程重启即清空，不做持久化。
_version_history: dict[str, list[dict[str, Any]]] = {}


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
        "enabled": skill.enabled,
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

    # 先查是否已有同名 skill → 用来判断 replaced + 记录版本历史
    existing = repo.get_by_name(name)
    was_runtime = existing is not None
    if existing is not None:
        # 覆盖注册：把被替换的旧版本快照记入内存版历史（新版本在前）
        history = _version_history.setdefault(name, [])
        history.insert(
            0,
            {
                "version": existing.version,
                "description": existing.description,
                "source": _LAYER_LABEL.get(
                    existing.metadata.get("__layer__") if existing.metadata else None, "runtime"
                ),
                "replaced_at": _utc_now_iso(),
            },
        )

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


# ---------------------------------------------------------------------------
# 版本历史 / 启用禁用
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    """当前 UTC 时间的 ISO 字符串，用于版本历史的 replaced_at 字段。"""
    return datetime.now(UTC).isoformat(timespec="seconds")


async def patch_skill(name: str, *, enabled: bool) -> dict[str, Any] | None:
    """启用/禁用一个 Skill（任意来源层均可，进程内内存态）。

    禁用后 SkillTrigger 不再命中该 Skill，但定义保留在仓库里，
    重新启用立即恢复，无需重新注册。

    Returns:
        更新后的 SkillItem dict；名字不存在返回 None。
    """
    repo = get_skill_repository()
    if not repo.loaded:
        await repo.load_all()

    skill = repo.set_enabled(name, enabled)
    if skill is None:
        return None

    log.info("SkillService.patch_skill: %s enabled=%s", name, enabled)
    return _skill_to_item(skill)


async def list_skill_versions(name: str) -> list[dict[str, Any]]:
    """查一个 Skill 的历史版本（内存态，仅记录被覆盖注册的旧版本）。

    不含当前生效版本（当前版本请走 GET /skills/{name}）。
    进程重启后历史清空，从当前版本重新开始记录。
    """
    repo = get_skill_repository()
    if not repo.loaded:
        await repo.load_all()

    if repo.get_by_name(name) is None:
        return []
    return list(_version_history.get(name, []))


__all__ = [
    "get_skill_repository",
    "init_skill_repository",
    "list_skills",
    "get_skill",
    "register_skill",
    "patch_skill",
    "list_skill_versions",
    "delete_skill",
    "trigger_test",
]
