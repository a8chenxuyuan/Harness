"""Agent 流式接口：POST /api/v1/agents/run/stream（SSE）。

- 请求体复用 ``AgentRunRequest``，仅支持 mode=single
- 开流前先校验会话归属，不存在 / 越权直接 404
- 生成过程使用独立 DB session，随 SSE 生命周期存活；
  客户端断线时由 ChatStreamService 把消息置为 failed
- ``POST /runs/{run_id}/cancel`` 登记协作式取消，由流在下个事件前收尾
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from harness.platform.api.deps import get_current_user, get_db
from harness.platform.api.dto.agent_dto import AgentRunRequest
from harness.platform.api.exceptions import BizError
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse
from harness.platform.api.vo.plan_vo import AgentCancelResponse
from harness.platform.service.message_service import MessageService
from harness.platform.service.rate_limit import stream_rate_limit
from harness.platform.service.stream_service import ChatStreamService, StreamEvent

router = APIRouter(prefix="/agents", tags=["agents"])
log = logging.getLogger(__name__)

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _encode(event_id: int, event: StreamEvent) -> str:
    """把领域事件编码成 SSE 帧（id / event / data）。"""
    data = json.dumps(event.data, ensure_ascii=False)
    return f"id: {event_id}\nevent: {event.event}\ndata: {data}\n\n"


@router.post("/run/stream")
async def run_agent_stream(
    req: AgentRunRequest,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description="幂等键（可选）"
    ),
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _rate: None = Depends(stream_rate_limit),
):
    """流式运行单 Agent，按 SSE 推送增量事件。

    传 ``Idempotency-Key`` 时：同 key 重复请求直接 409 + run_id（流式不缓存回放）。
    """
    from harness.platform.api.idempotency_helpers import (
        conflict_response,
        normalize_key,
    )
    from harness.platform.service.idempotency_service import (
        SCOPE_STREAM,
        IdempotencyService,
        hash_request,
    )

    if not req.conversation_id:
        raise BizError(400, "conversation_id is required for streaming")
    if req.mode != "single":
        raise BizError(400, "streaming only supports mode=single")

    # 先校验会话归属：不存在 / 越权在开流前直接 404
    await MessageService(user, db).ensure_session(req.conversation_id)

    key = normalize_key(idempotency_key)
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    record_id: str | None = None
    if key is not None:
        claim = await IdempotencyService(db).claim(
            user.tenant_id,
            SCOPE_STREAM,
            key,
            hash_request(req.model_dump()),
            run_id=run_id,
            replay_completed=False,
        )
        if claim.conflict:
            return conflict_response(claim)
        if claim.record is not None:
            record_id = claim.record.id

    # 配额检查在开流前完成：超限直接返回 429，不建立 SSE
    from harness.platform.service.quota_service import QuotaService

    quota = QuotaService(db)
    await quota.ensure_available(user.tenant_id)
    await quota.record_run_started(user.tenant_id)

    async def _events() -> AsyncIterator[str]:
        # 独立 DB session：随 SSE 生命周期存活，不依赖请求依赖的清理时机
        from harness.platform.infra.engine import get_session_factory

        factory = get_session_factory()
        finished = False
        try:
            async with factory() as session:
                service = ChatStreamService(user, session)
                event_id = 0
                async for event in service.stream(
                    req.conversation_id, req.goal, run_id=run_id
                ):
                    event_id += 1
                    yield _encode(event_id, event)
            finished = True
        finally:
            await _finalize_idempotency(factory, record_id, run_id, finished)

    return StreamingResponse(
        _events(), media_type="text/event-stream", headers=_SSE_HEADERS
    )


async def _finalize_idempotency(factory, record_id: str | None, run_id: str, ok: bool) -> None:
    """流结束后用独立 session 收尾幂等记录。"""
    if record_id is None:
        return
    try:
        from harness.platform.service.idempotency_service import IdempotencyService

        async with factory() as session:
            service = IdempotencyService(session)
            if ok:
                await service.complete_by_id(record_id, {"run_id": run_id})
            else:
                await service.release_by_id(record_id)
    except Exception as exc:  # noqa: BLE001 — 收尾失败不影响已发送内容
        log.warning("idempotency: 流式收尾失败 record=%s err=%s", record_id, exc)


@router.post("/runs/{run_id}/cancel", response_model=ApiResponse[AgentCancelResponse])
async def cancel_stream_run(
    run_id: str,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """请求取消流式运行。

    活跃流返回 ``cancelling``（由 SSE 流在下一个事件前收尾）；
    无活跃流（重启 / 已断线）时直接落 ``cancelled`` 并清理残留 streaming 消息。
    """
    from harness.platform.auth.audit import record_audit
    from harness.platform.service.stream_cancel import StreamCancelService

    result = await StreamCancelService(user, db).cancel(run_id)
    await record_audit(
        db,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        action="run.cancel",
        target=run_id,
        result="success" if result["status"] != "cancelling" else "accepted",
    )
    return {"code": 0, "message": "ok", "data": result}


__all__ = ["router"]
