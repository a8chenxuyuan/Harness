"""Memory 管理接口（W4-02）。

对外暴露长期记忆的查询、手动保存、删除能力。
长期记忆是 Agent 的"外部大脑"——跨会话持久化存储，
LLM 可通过 memory_search / memory_save 工具自主访问；
本模块是给人看的管理接口，让运维/用户可以直接 CRUD。

接口清单：
    GET    /memories                 分页列表（支持关键词搜索 + session 筛选）
    POST   /memories                 手动保存一条记忆
    DELETE /memories/{item_id}       删除记忆
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from harness.platform.api.deps import get_current_user
from harness.platform.api.dto.memory_dto import MemorySaveRequest
from harness.platform.api.exceptions import BizError
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse
from harness.platform.api.vo.memory_vo import (
    MemoryDeleteResponse,
    MemoryItemVO,
    MemoryListResponse,
    MemorySaveResponse,
    memory_item_to_vo_dict,
    _ts_to_iso,
)
from harness.platform.service import memory_service

router = APIRouter(prefix="/memories", tags=["memories"])


# ---------------------------------------------------------------------------
# GET /memories —— 分页列表
# ---------------------------------------------------------------------------

@router.get("", response_model=ApiResponse[MemoryListResponse])
async def list_memories(
    keyword: str = Query(default="", max_length=200, description="关键词（LIKE 匹配），空则返回全部"),
    limit: int = Query(default=50, ge=1, le=500, description="每页条数，默认 50"),
    offset: int = Query(default=0, ge=0, description="分页偏移，默认 0"),
    session_id: str | None = Query(default=None, max_length=64, description="限定来源会话；空表示不筛选"),
    user: UserInfo = Depends(get_current_user),
) -> dict:
    """分页查询长期记忆。

    支持：
        - keyword 关键词（SQL LIKE，大小写不敏感）
        - session_id 限定来源会话（空串=全局）
        - limit + offset 分页

    返回的 total 是不受 limit/offset 限制的总数，
    方便前端做"共 X 条"的分页展示。
    """
    items, total = await memory_service.list_memories(
        keyword=keyword,
        limit=limit,
        offset=offset,
        session_id=session_id,
    )
    return {
        "code": 0,
        "message": "ok",
        "data": MemoryListResponse(
            items=[MemoryItemVO(**memory_item_to_vo_dict(i)) for i in items],
            total=total,
            limit=limit,
            offset=offset,
        ),
    }


# ---------------------------------------------------------------------------
# POST /memories —— 手动保存
# ---------------------------------------------------------------------------

@router.post("", response_model=ApiResponse[MemorySaveResponse])
async def save_memory(
    body: MemorySaveRequest,
    user: UserInfo = Depends(get_current_user),
) -> dict:
    """手动保存一条长期记忆。

    用户主动存的记忆不需要审核（因为是自己存的），
    直接写入 LongTermMemory。保存后立即可被 Agent 的
    memory_search 工具检索到。
    """
    item_id, ts = await memory_service.save_memory(
        content=body.content,
        session_id=body.session_id,
        tags=body.tags,
        metadata=body.metadata,
    )
    return {
        "code": 0,
        "message": "ok",
        "data": MemorySaveResponse(
            item_id=item_id,
            created_at=_ts_to_iso(ts),
        ),
    }


# ---------------------------------------------------------------------------
# DELETE /memories/{item_id} —— 删除
# ---------------------------------------------------------------------------

@router.delete("/{item_id}", response_model=ApiResponse[MemoryDeleteResponse])
async def delete_memory(
    item_id: str,
    user: UserInfo = Depends(get_current_user),
) -> dict:
    """按 item_id 删除一条记忆。

    - 不存在 → BizError(404)
    - 删除成功 → deleted=true
    """
    deleted = await memory_service.delete_memory(item_id)
    if not deleted:
        raise BizError(status.HTTP_404_NOT_FOUND, f"memory {item_id} not found")
    return {
        "code": 0,
        "message": "ok",
        "data": MemoryDeleteResponse(deleted=True),
    }


__all__ = ["router"]
