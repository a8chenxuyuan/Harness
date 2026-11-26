"""Memory 管理接口入参（DTO）。

长期记忆（LongTermMemory）是 Agent 跨会话的"外部大脑"，
LLM 可以通过 memory_search / memory_save 工具自主检索和保存。
本模块是给人看的管理接口，让运维/用户可以直接 CRUD 记忆。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MemorySaveRequest(BaseModel):
    """POST /memories 请求体 —— 手动保存一条长期记忆。

    用户主动存的记忆不需要审核（因为是自己存的），
    直接写入 LongTermMemory。
    """

    content: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="记忆正文（关键词匹配的核心）",
    )
    session_id: str | None = Field(
        default=None,
        max_length=64,
        description="来源会话 ID；为空表示全局记忆",
    )
    tags: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="标签列表，写入 metadata.tags 供后续筛选",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展字段（不建议直接用，优先用 tags/session_id）",
    )


class MemorySearchQuery(BaseModel):
    """GET /memories 查询参数封装（FastAPI 会自动把 query string 映射过来）。"""

    keyword: str = Field(default="", max_length=200, description="关键词（LIKE 匹配）；为空返回全部")
    limit: int = Field(default=50, ge=1, le=500, description="返回条数上限")
    offset: int = Field(default=0, ge=0, description="分页偏移")
    session_id: str | None = Field(default=None, description="限定来源会话；为空返回全局+所有会话")


__all__ = ["MemorySaveRequest", "MemorySearchQuery"]
