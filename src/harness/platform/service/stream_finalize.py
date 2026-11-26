"""流式运行收尾 — 消息终态与运行记录落库。

从 ``stream_service`` 抽出，保证单个文件不超过 300 行；
本模块只做持久化收尾，不关心流式事件如何产生。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.message_vo import MessageResponse
from harness.platform.entity.agent_run import AgentRun
from harness.platform.entity.session_message import SessionMessage
from harness.platform.repository.agent_run_repository import AgentRunRepository
from harness.platform.service.message_service import MessageService
from harness.platform.service.stream_events import StreamEvent

log = logging.getLogger(__name__)

# 消息终态 → 运行记录终态
_RUN_STATUS = {
    "completed": "succeeded",
    "cancelled": "cancelled",
    "failed": "failed",
}


async def finalize_stream(
    user: UserInfo,
    db: AsyncSession,
    message: SessionMessage,
    record: AgentRun,
    *,
    status: str,
    text: str,
    parts: list[dict[str, Any]],
    error: str | None,
    metrics: dict[str, int],
) -> MessageResponse:
    """落消息终态 + 运行终态，返回最终消息快照。"""
    response = await MessageService(user, db).finish_streaming_message(
        message, text=text, parts=parts, status=status
    )
    now = datetime.now(timezone.utc)
    record.status = _RUN_STATUS.get(status, "failed")
    record.output = text or None
    record.error = error
    record.token_usage = json.dumps(metrics or {}, ensure_ascii=False)
    record.finished_at = now
    record.updated_at = now
    try:
        await AgentRunRepository(db).save(record)
    except Exception:  # noqa: BLE001 — 运行记录失败不影响消息终态
        log.exception("stream: 运行记录落库失败 run=%s", record.run_id)
    return response


async def cleanup_interrupted(
    user: UserInfo,
    message_id: str,
    run_id: str,
    text: str,
    parts: list[dict[str, Any]],
    error: str,
) -> None:
    """断线收尾：用独立 DB session 把消息与运行记录置为 failed。

    断线时当前任务处于取消上下文，原 session 的后续 await 会被再次取消，
    因此必须新开连接、在独立任务中完成收尾。
    """
    from harness.platform.infra.engine import get_session_factory

    try:
        factory = get_session_factory()
        async with factory() as session:
            messages = MessageService(user, session)
            message = await messages.messages.get(message_id)
            if message is not None:
                await messages.finish_streaming_message(
                    message, text=text, parts=parts, status="failed"
                )
            runs = AgentRunRepository(session)
            record = await runs.get(run_id)
            if record is None:
                return
            now = datetime.now(timezone.utc)
            record.status = "failed"
            record.output = text or None
            record.error = error
            record.finished_at = now
            record.updated_at = now
            await runs.save(record)
    except Exception:  # noqa: BLE001 — 收尾失败只记日志，避免任务异常逃逸
        log.exception("stream: 断线收尾失败 message=%s", message_id)


def end_event(
    response: MessageResponse,
    status: str,
    metrics: dict[str, int],
    error: str | None,
) -> StreamEvent:
    """组装 message_end 事件（携带最终消息快照）。"""
    return StreamEvent(
        "message_end",
        {
            "status": status,
            "message": response.model_dump(mode="json"),
            "metrics": metrics,
            "error": error,
        },
    )


__all__ = ["finalize_stream", "cleanup_interrupted", "end_event"]
