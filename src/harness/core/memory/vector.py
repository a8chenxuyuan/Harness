"""VectorMemory — 带向量重排的长期记忆（Phase 24）。

设计取舍：
    - **不引入向量库**。先用 MemoryRepository 的 LIKE 做候选召回，
      再用 EmbeddingProvider 对候选做余弦相似度重排。
    - 未注入 provider / provider 抛错 / 向量维度不一致 → 自动降级为
      LIKE 时间倒序结果（与 LongTermMemory 一致的语义）。
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Protocol, runtime_checkable

from .base import Memory, MemoryItem

log = logging.getLogger(__name__)


@runtime_checkable
class EmbeddingProvider(Protocol):
    """向量化提供方契约（OpenAI / 本地 sentence-transformers 均可实现）。"""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """把一批文本编码成向量。"""
        ...


def _cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度；任一零向量返回 0。"""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class VectorMemory(Memory):
    """基于 MemoryRepository + EmbeddingProvider 的记忆实现。

    Args:
        session_factory: 返回 AsyncSession 的工厂（``get_session_factory()``）。
        provider: 可选向量化提供方；None 时纯 LIKE 模式。
        tenant_id / user_id: 记忆归属（租户隔离）。
        candidate_limit: LIKE 召回候选上限（重排前）。
    """

    def __init__(
        self,
        session_factory,
        *,
        provider: EmbeddingProvider | None = None,
        tenant_id: str = "default",
        user_id: str = "default",
        candidate_limit: int = 50,
    ) -> None:
        self._factory = session_factory
        self._provider = provider
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._candidate_limit = candidate_limit

    # --- Memory 接口 -----------------------------------------------------------

    async def save(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
        session_id: str = "",
    ) -> str:
        """写入记忆；provider 可用时额外把向量写进 metadata 以便重排。"""
        enriched = dict(metadata or {})
        if self._provider is not None:
            vector = await self._safe_embed([text])
            if vector:
                enriched["_embedding"] = vector[0]

        from harness.platform.repository.memory_repo import MemoryRepository

        async with self._factory() as session:
            return await MemoryRepository(session).save(
                tenant_id=self._tenant_id,
                user_id=self._user_id,
                content=text,
                metadata=enriched,
                session_id=session_id or None,
            )

    async def search(self, query: str, limit: int = 5) -> list[MemoryItem]:
        """LIKE 召回 + 向量重排；无 provider 时退化为时间倒序。"""
        if not query:
            return []

        from harness.platform.repository.memory_repo import MemoryRepository

        async with self._factory() as session:
            rows = await MemoryRepository(session).search(
                self._tenant_id,
                query,
                limit=max(limit, self._candidate_limit),
            )

        items = [self._to_item(row) for row in rows]
        if self._provider is None or len(items) <= 1:
            return items[:limit]

        vectors = await self._safe_embed(
            [query] + [item.text for item in items]
        )
        if len(vectors) != len(items) + 1:
            return items[:limit]

        query_vec, doc_vecs = vectors[0], vectors[1:]
        scored = sorted(
            zip(items, doc_vecs),
            key=lambda pair: _cosine(query_vec, pair[1]),
            reverse=True,
        )
        return [item for item, _ in scored][:limit]

    async def delete(self, item_id: str) -> bool:
        """删除一条记忆（租户隔离）。"""
        from harness.platform.repository.memory_repo import MemoryRepository

        async with self._factory() as session:
            return await MemoryRepository(session).delete(self._tenant_id, item_id)

    # --- 内部 -----------------------------------------------------------------

    async def _safe_embed(self, texts: list[str]) -> list[list[float]]:
        """调用 provider；异常时返回空列表（触发降级）。"""
        try:
            vectors = await self._provider.embed(texts)  # type: ignore[union-attr]
            if not isinstance(vectors, list) or len(vectors) != len(texts):
                return []
            return vectors
        except Exception as exc:  # noqa: BLE001
            log.warning("VectorMemory: embedding 失败，降级 LIKE: %s", exc)
            return []

    @staticmethod
    def _to_item(row) -> MemoryItem:
        try:
            meta = json.loads(row.metadata_json or "{}")
        except json.JSONDecodeError:
            meta = {}
        return MemoryItem(
            item_id=row.id,
            text=row.content,
            metadata=meta if isinstance(meta, dict) else {},
            created_at=row.created_at.timestamp(),
            session_id=row.session_id or "",
        )


__all__ = ["EmbeddingProvider", "VectorMemory"]
