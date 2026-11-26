"""Memory 管理接口出参（VO）。

请求模型在 ``api.dto.memory_dto``。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class MemoryItemVO(BaseModel):
    """单条长期记忆的展示项。"""

    item_id: str = Field(..., description="UUID 主键")
    content: str = Field(..., description="记忆正文")
    session_id: str = Field(default="", description="来源会话；空串表示全局")
    tags: list[str] = Field(default_factory=list, description="标签列表（从 metadata.tags 提取）")
    metadata: dict[str, Any] = Field(default_factory=dict, description="剩余扩展字段（不含 tags）")
    created_at: str = Field(..., description="ISO-8601 UTC 时间（如 2026-11-26T10:00:00Z）")


class MemoryListResponse(BaseModel):
    """GET /memories 响应体。"""

    items: list[MemoryItemVO] = Field(default_factory=list, description="记忆项列表，按创建时间倒序")
    total: int = Field(default=0, description="总数（不受 limit/offset 限制）")
    limit: int = Field(default=50, description="请求时的 limit")
    offset: int = Field(default=0, description="请求时的 offset")


class MemorySaveResponse(BaseModel):
    """POST /memories 响应体。"""

    item_id: str = Field(..., description="新保存的记忆 UUID")
    created_at: str = Field(..., description="ISO-8601 UTC 时间")


class MemoryDeleteResponse(BaseModel):
    """DELETE /memories/{id} 响应体。"""

    deleted: bool = Field(default=True, description="true=确实删除了；false=item_id 不存在")


# ---------------------------------------------------------------------------
# 工具函数：把 core 层 MemoryItem dataclass 转成 API VO 需要的 dict
# ---------------------------------------------------------------------------

def _ts_to_iso(ts: float) -> str:
    """把 time.time() 秒级时间戳转 ISO-8601 UTC 字符串。

    SQLite 存的 created_at 是 float（秒），前端要人类可读的 UTC 时间。
    """
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def memory_item_to_vo_dict(item) -> dict[str, Any]:
    """把 core 层 MemoryItem dataclass 转成 MemoryItemVO 所需的 dict。

    额外处理：
        - 从 metadata 里提取 ``tags`` 字段（list[str]）作为顶层字段，
          方便前端直接展示标签，不用挖 metadata
        - created_at 从 float 时间戳转 ISO-8601 字符串
    """
    metadata = dict(item.metadata) if item.metadata else {}
    tags = metadata.pop("tags", [])
    # 兼容：如果 metadata.tags 不是 list，给空列表
    if not isinstance(tags, list):
        tags = []
    return {
        "item_id": item.item_id,
        "content": item.text,
        "session_id": item.session_id or "",
        "tags": list(tags),
        "metadata": metadata,
        "created_at": _ts_to_iso(item.created_at),
    }


__all__ = [
    "MemoryItemVO",
    "MemoryListResponse",
    "MemorySaveResponse",
    "MemoryDeleteResponse",
    "memory_item_to_vo_dict",
]
