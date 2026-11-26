"""Agent 流式接口：POST /api/v1/agents/run/stream（SSE）。

- 请求体复用 ``AgentRunRequest``，仅支持 mode=single
- 开流前先校验会话归属，不存在 / 越权直接 404
- 生成过程使用独立 DB session，随 SSE 生命周期存活；
  客户端断线时由 ChatStreamService 把消息置为 failed
- ``POST /runs/{run_id}/cancel`` 登记协作式取消，由流在下个事件前收尾
"""

from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from harness.platform.api.deps import get_current_user, get_db
from harness.platform.api.dto.agent_dto import AgentRunRequest
from harness.platform.api.exceptions import BizError
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse
from harness.platform.api.vo.plan_vo import AgentCancelResponse
from harness.platform.service.message_service import MessageService
from harness.platform.service.stream_service import ChatStreamService, StreamEvent

router = APIRouter(prefix="/agents", tags=["agents"])

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
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """流式运行单 Agent，按 SSE 推送增量事件。"""
    if not req.conversation_id:
        raise BizError(400, "conversation_id is required for streaming")
    if req.mode != "single":
        raise BizError(400, "streaming only supports mode=single")

    # 先校验会话归属：不存在 / 越权在开流前直接 404
    await MessageService(user, db).ensure_session(req.conversation_id)

    async def _events() -> AsyncIterator[str]:
        # 独立 DB session：随 SSE 生命周期存活，不依赖请求依赖的清理时机
        from harness.platform.infra.engine import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            service = ChatStreamService(user, session)
            event_id = 0
            async for event in service.stream(req.conversation_id, req.goal):
                event_id += 1
                yield _encode(event_id, event)

    return StreamingResponse(
        _events(), media_type="text/event-stream", headers=_SSE_HEADERS
    )


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
