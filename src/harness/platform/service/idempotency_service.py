"""幂等键应用服务（W3-KERN-02）。

用法（Controller）::

    result = await IdempotencyService(db).claim(
        tenant_id, "agent.run", key, request_hash, run_id=run_id
    )
    if result.cached is not None:
        return cached            # 同步接口回放
    if result.conflict:
        raise BizError(409, ...) # 重复请求
    record = result.record       # 本次请求占据的幂等记录
    ...
    await service.complete(record, data)

请求哈希用于检测「同一个 key 换了 body」：命中直接 409，避免把旧响应
错误回放给新请求。
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

log = logging.getLogger(__name__)

SCOPE_RUN = "agent.run"
SCOPE_STREAM = "agent.run.stream"

MAX_KEY_LENGTH = 128


@dataclass
class ClaimResult:
    """幂等占位结果。

    Attributes:
        record: 本次请求持有的记录（None 表示无需处理）。
        cached: 已成功请求的缓存响应（同步接口直接回放）。
        conflict: 冲突原因：``hash_mismatch`` / ``in_progress``。
        run_id: 冲突记录关联的运行 id（流式接口 409 时返回给前端）。
    """

    record: object | None = None
    cached: dict | None = None
    conflict: str | None = None
    run_id: str | None = None


def hash_request(payload: dict) -> str:
    """对请求体做稳定哈希（键排序 + 紧凑 JSON）。"""
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class IdempotencyService:
    """幂等键占位 / 回放 / 完成 / 释放。"""

    def __init__(self, session) -> None:
        from harness.platform.repository.idempotency_repository import (
            IdempotencyRepository,
        )

        self.repo = IdempotencyRepository(session)

    async def claim(
        self,
        tenant_id: str,
        scope: str,
        key: str,
        request_hash: str,
        *,
        run_id: str | None = None,
        replay_completed: bool = True,
    ) -> ClaimResult:
        """尝试占位；已有记录时按状态返回缓存或冲突。

        Args:
            replay_completed: True 时同步接口可回放已成功响应；
                False 时流式接口对任何已存在记录都返回 409。
        """
        existing = await self.repo.lookup(tenant_id, scope, key)
        if existing is not None:
            if existing.request_hash != request_hash:
                return ClaimResult(conflict="hash_mismatch", run_id=existing.run_id)
            if replay_completed and existing.status == "succeeded":
                cached = self.loads(existing)
                if cached is not None:
                    return ClaimResult(cached=cached, run_id=existing.run_id)
            return ClaimResult(conflict="in_progress", run_id=existing.run_id)

        from harness.platform.entity.idempotency_key import IdempotencyRecord

        record = IdempotencyRecord(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            scope=scope,
            key=key,
            request_hash=request_hash,
            status="in_progress",
            run_id=run_id,
        )
        if await self.repo.add(record):
            return ClaimResult(record=record, run_id=run_id)

        # 并发冲突：另一请求刚插入，重新按已有记录处理
        return await self.claim(
            tenant_id,
            scope,
            key,
            request_hash,
            run_id=run_id,
            replay_completed=replay_completed,
        )

    async def complete(self, record, response: dict) -> None:
        """成功完成：缓存响应并按需补 run_id。"""
        payload = json.dumps(response, ensure_ascii=False)
        if record.run_id is None and isinstance(response.get("run_id"), str):
            record.run_id = response["run_id"]
        await self.repo.complete(record, payload)

    async def release(self, record) -> None:
        """失败释放：删除占位，允许同 key 重试。"""
        await self.repo.delete(record)

    async def complete_by_id(self, record_id: str, response: dict) -> None:
        """按 id 完成（流式生成器用独立 session 收尾）。"""
        from harness.platform.entity.idempotency_key import IdempotencyRecord

        record = await self.repo.session.get(IdempotencyRecord, record_id)
        if record is None:
            return
        await self.complete(record, response)

    async def release_by_id(self, record_id: str) -> None:
        """按 id 释放（流式失败 / 断线）。"""
        from harness.platform.entity.idempotency_key import IdempotencyRecord

        record = await self.repo.session.get(IdempotencyRecord, record_id)
        if record is not None:
            await self.repo.delete(record)

    @staticmethod
    def loads(record) -> dict | None:
        """解析缓存响应；损坏时返回 None（按冲突处理）。"""
        raw = getattr(record, "response_json", None)
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            log.warning("idempotency: 缓存响应损坏 id=%s", getattr(record, "id", "?"))
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def now() -> datetime:
        """当前 UTC 时间（便于测试替换）。"""
        return datetime.now(timezone.utc)


__all__ = [
    "ClaimResult",
    "IdempotencyService",
    "MAX_KEY_LENGTH",
    "SCOPE_RUN",
    "SCOPE_STREAM",
    "hash_request",
]
