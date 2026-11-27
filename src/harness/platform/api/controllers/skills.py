"""Skill 管理接口（W4-01）。

对外暴露已加载 Skill 的查询、注册、注销与触发测试。
Skill 是 Agent 的"人格/专家视角包"——命中触发词时追加 custom_message
到会话 history，**不修改 stable_prefix**，确保前缀缓存不失效。

接口清单：
    GET    /skills                 列出当前运行时加载的全部 Skill
    GET    /skills/{name}          查单个 Skill 详情
    POST   /skills                 注册一个新 Skill（运行时层，同名覆盖）
    PATCH  /skills/{name}          启用/禁用一个 Skill（任意来源层，内存态）
    GET    /skills/{name}/versions 查历史版本（内存态，仅记录被覆盖注册的旧版本）
    DELETE /skills/{name}          注销运行时 Skill（低层 Skill 不允许 API 删）
    POST   /skills/trigger-test    传一段文本，返回命中的 Skill 列表（仅匹配不激活）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from harness.platform.api.deps import require_role
from harness.platform.api.dto.skill_dto import (
    SkillPatchRequest,
    SkillRegisterRequest,
    SkillTriggerTestRequest,
)
from harness.platform.api.exceptions import BizError
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse
from harness.platform.api.vo.skill_vo import (
    SkillDeleteResponse,
    SkillDetailResponse,
    SkillItem,
    SkillListResponse,
    SkillPatchResponse,
    SkillRegisterResponse,
    SkillTriggerMatch,
    SkillTriggerTestResponse,
    SkillVersionItem,
    SkillVersionsResponse,
)
from harness.platform.service import skill_service as skills

router = APIRouter(prefix="/skills", tags=["skills"])


# ---------------------------------------------------------------------------
# GET /skills —— 列表
# ---------------------------------------------------------------------------

@router.get("", response_model=ApiResponse[SkillListResponse])
async def list_skills(user: UserInfo = Depends(require_role("owner", "admin", "machine"))) -> dict:
    """列出当前全部 Skill。

    按四层聚合优先级从高到低排序：runtime → user → project → bundled。
    每个 Skill 附带 source 字段标识来源层。
    """
    items = await skills.list_skills()
    return {
        "code": 0,
        "message": "ok",
        "data": SkillListResponse(
            items=[SkillItem(**i) for i in items],
            total=len(items),
        ),
    }


# ---------------------------------------------------------------------------
# GET /skills/{name} —— 详情
# ---------------------------------------------------------------------------

@router.get("/{name}", response_model=ApiResponse[SkillDetailResponse])
async def get_skill(name: str, user: UserInfo = Depends(require_role("owner", "admin", "machine"))) -> dict:
    """按名字查 Skill，不存在返回 data.skill=null（不是 404）。

    原因：Skill 是动态加载的，不同环境 bundled/project 目录内容可能不同，
    前端拿到 null 后自己决定怎么展示"未找到"。
    """
    item = await skills.get_skill(name)
    return {
        "code": 0,
        "message": "ok",
        "data": SkillDetailResponse(
            skill=SkillItem(**item) if item else None,
        ),
    }


# ---------------------------------------------------------------------------
# POST /skills —— 注册
# ---------------------------------------------------------------------------

@router.post("", response_model=ApiResponse[SkillRegisterResponse])
async def register_skill(
    body: SkillRegisterRequest,
    user: UserInfo = Depends(require_role("owner", "admin", "machine")),
) -> dict:
    """注册一个新 Skill（运行时层）。

    运行时层优先级最高，会覆盖 bundled/project/user 的同名版本。
    重名注册不报错——这是有意设计：允许热更新 Skill 定义。

    注册的 Skill 只在当前进程存活，进程重启后会重新从文件系统加载。
    如果要持久化，请写到 ``{cwd}/.harness/skills/`` 项目目录下。
    """
    item_dict, replaced = await skills.register_skill(
        name=body.name,
        description=body.description,
        version=body.version,
        triggers=body.triggers,
        tools=body.tools,
        custom_message=body.custom_message,
        metadata=body.metadata,
    )
    return {
        "code": 0,
        "message": "ok",
        "data": SkillRegisterResponse(
            skill=SkillItem(**item_dict),
            replaced=replaced,
        ),
    }


# ---------------------------------------------------------------------------
# PATCH /skills/{name} —— 启用/禁用
# ---------------------------------------------------------------------------

@router.patch("/{name}", response_model=ApiResponse[SkillPatchResponse])
async def patch_skill(
    name: str,
    body: SkillPatchRequest,
    user: UserInfo = Depends(require_role("owner", "admin", "machine")),
) -> dict:
    """启用/禁用一个 Skill。

    任意来源层（runtime/user/project/bundled）均可操作，状态为进程内
    内存态：禁用后 SkillTrigger 不再命中、SkillActivator 不会激活，
    但 Skill 定义保留；重新启用立即恢复，无需重新注册。

    - 找不到 → BizError(404)
    """
    item = await skills.patch_skill(name, enabled=body.enabled)
    if item is None:
        raise BizError(status.HTTP_404_NOT_FOUND, f"skill {name} not found")
    return {
        "code": 0,
        "message": "ok",
        "data": SkillPatchResponse(skill=SkillItem(**item)),
    }


# ---------------------------------------------------------------------------
# GET /skills/{name}/versions —— 历史版本
# ---------------------------------------------------------------------------

@router.get("/{name}/versions", response_model=ApiResponse[SkillVersionsResponse])
async def list_skill_versions(name: str, user: UserInfo = Depends(require_role("owner", "admin", "machine"))) -> dict:
    """查一个 Skill 的历史版本（内存态）。

    只记录 API 覆盖注册时被替换的旧版本，新版本在前；
    当前生效版本不含在内。进程重启后历史清空。
    Skill 不存在时返回空列表（不报 404，与详情接口的宽松风格一致）。
    """
    items = await skills.list_skill_versions(name)
    return {
        "code": 0,
        "message": "ok",
        "data": SkillVersionsResponse(
            items=[SkillVersionItem(**i) for i in items],
            total=len(items),
        ),
    }


# ---------------------------------------------------------------------------
# DELETE /skills/{name} —— 注销
# ---------------------------------------------------------------------------

@router.delete("/{name}", response_model=ApiResponse[SkillDeleteResponse])
async def delete_skill(name: str, user: UserInfo = Depends(require_role("owner", "admin", "machine"))) -> dict:
    """注销一个 Skill。

    ⚠️ **安全限制**：只允许注销运行时层注册的 Skill。
    bundled/project/user 层的 Skill 来自文件系统，API 不允许删除，
    必须通过文件管理操作（避免误删内置 Skill）。

    - 找不到 → BizError(404)
    - 来自低层 → BizError(403)（提示去文件系统操作）
    - 注销成功 → deleted=true
    """
    item = await skills.get_skill(name)
    if item is None:
        raise BizError(status.HTTP_404_NOT_FOUND, f"skill {name} not found")

    deleted = await skills.delete_skill(name)
    if not deleted:
        # 低层 Skill 不允许 API 删
        raise BizError(
            status.HTTP_403_FORBIDDEN,
            f"skill {name} comes from {item.get('source')} layer, delete via filesystem",
        )
    return {
        "code": 0,
        "message": "ok",
        "data": SkillDeleteResponse(deleted=True),
    }


# ---------------------------------------------------------------------------
# POST /skills/trigger-test —— 触发测试
# ---------------------------------------------------------------------------

@router.post("/trigger-test", response_model=ApiResponse[SkillTriggerTestResponse])
async def trigger_test(
    body: SkillTriggerTestRequest,
    user: UserInfo = Depends(require_role("owner", "admin", "machine")),
) -> dict:
    """测试 Skill 匹配效果：传一段文本，返回命中的 Skill 列表。

    仅做匹配不做激活，安全无害。每个命中项额外返回具体命中的 trigger
    字符串（关键词或正则 pattern），方便前端展示"哪条规则命中了这个 skill"。

    匹配规则：
        - /regex/  → 正则，re.IGNORECASE
        - 其他     → 关键词包含（大小写不敏感）
    """
    matched = await skills.trigger_test(body.text)
    return {
        "code": 0,
        "message": "ok",
        "data": SkillTriggerTestResponse(
            matched=[SkillTriggerMatch(**m) for m in matched],
            total_matches=len(matched),
        ),
    }


__all__ = ["router"]
