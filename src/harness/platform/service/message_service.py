"""消息应用服务 — 会话消息的读写与 sessions 计数维护。

职责：
    - 校验会话归属（租户 + 属主），越权一律 404
    - 追加消息（seq 会话内单调递增），同步刷新 sessions.message_count /
      last_message_at
    - 按 seq 游标分页读取，返回 has_more 供前端判断是否继续拉取
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from harness.platform.api.dto.message_dto import MessageCreateRequest
from harness.platform.api.exceptions import BizError
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.message_vo import MessageListResponse, MessageResponse
from harness.platform.entity.session_message import SessionMessage
from harness.platform.repository.session_message_repository import (
    SessionMessageRepository,
)
from harness.platform.repository.session_repository import SessionRepository
from harness.platform.service.session_title import build_title, needs_auto_title


class MessageService:
    """会话消息用例。"""

    def __init__(self, user: UserInfo, db) -> None:
        self.user = user
        self.session = db
        self.messages = SessionMessageRepository(db)
        self.sessions = SessionRepository(db)

    async def list_messages(
        self, session_id: str, *, after_seq: int = 0, limit: int = 50
    ) -> MessageListResponse:
        """按 seq 游标读取消息（升序）；会话不存在或不属于当前用户时 404。"""
        await self._require_session(session_id)

        records = await self.messages.list_by_session(
            self.user.tenant_id, session_id, after_seq=after_seq, limit=limit + 1
        )
        has_more = len(records) > limit
        items = [self._to_response(r) for r in records[:limit]]
        next_cursor = items[-1].seq if items else after_seq
        return MessageListResponse(
            items=items, next_cursor=next_cursor, has_more=has_more
        )

    async def append_message(
        self, session_id: str, req: MessageCreateRequest
    ) -> MessageResponse:
        """追加一条消息，并刷新会话的消息计数与活跃时间。"""
        record = await self._require_session(session_id)

        parts = list(req.parts)
        text = req.text.strip()
        if not parts and text:
            parts = [{"type": "text", "text": text}]
        if not text:
            text = self._extract_text(parts)

        seq = await self.messages.next_seq(self.user.tenant_id, session_id)
        now = datetime.now(timezone.utc)
        message = SessionMessage(
            id=f"msg-{session_id}-{seq}",
            session_id=session_id,
            tenant_id=self.user.tenant_id,
            user_id=self.user.user_id,
            role=req.role,
            parts=parts,
            text=text,
            seq=seq,
            parent_id=req.parent_id,
            status=req.status,
            created_at=now,
        )
        await self.messages.save(message)

        # 首条用户消息自动补标题：仅替换占位标题，不覆盖用户自定义命名
        if req.role == "user" and needs_auto_title(record.title):
            generated = build_title(text)
            if generated:
                record.title = generated

        record.message_count = await self.messages.count_by_session(
            self.user.tenant_id, session_id
        )
        record.last_message_at = now
        record.updated_at = now
        await self.sessions.save(record)

        return self._to_response(message)

    # ------------------------------------------------------------------
    # 流式消息（SSE 增量落库）
    # ------------------------------------------------------------------

    async def ensure_session(self, session_id: str) -> None:
        """校验会话存在且属于当前用户；不存在时抛 404。"""
        await self._require_session(session_id)

    async def start_streaming_message(
        self, session_id: str, *, parent_id: str | None = None
    ) -> SessionMessage:
        """创建 assistant 流式占位消息（status=streaming），并刷新会话计数。"""
        record = await self._require_session(session_id)
        seq = await self.messages.next_seq(self.user.tenant_id, session_id)
        now = datetime.now(timezone.utc)
        message = SessionMessage(
            id=f"msg-{session_id}-{seq}",
            session_id=session_id,
            tenant_id=self.user.tenant_id,
            user_id=self.user.user_id,
            role="assistant",
            parts=[],
            text="",
            seq=seq,
            parent_id=parent_id,
            status="streaming",
            created_at=now,
        )
        await self.messages.save(message)

        record.message_count = await self.messages.count_by_session(
            self.user.tenant_id, session_id
        )
        record.last_message_at = now
        record.updated_at = now
        await self.sessions.save(record)
        return message

    async def update_streaming_message(
        self,
        message: SessionMessage,
        *,
        text: str,
        parts: list[dict],
        status: str | None = None,
    ) -> None:
        """增量刷新流式消息的文本 / 内容块（节流由调用方控制）。

        parts 必须复制一份：若直接复用同一个列表对象原地追加，
        SQLAlchemy 不会把该列标记为脏数据，导致内容块刷不进库。
        """
        message.text = text
        message.parts = [dict(part) for part in parts]
        if status is not None:
            message.status = status
        await self.messages.save(message)

    async def finish_streaming_message(
        self,
        message: SessionMessage,
        *,
        text: str,
        parts: list[dict],
        status: str,
    ) -> MessageResponse:
        """流式结束：落终态（completed / failed）并刷新会话活跃时间。"""
        await self.update_streaming_message(
            message, text=text, parts=parts, status=status
        )
        record = await self.sessions.get_by_owner(
            self.user.tenant_id, self.user.user_id, message.session_id
        )
        if record is not None:
            now = datetime.now(timezone.utc)
            record.last_message_at = now
            record.updated_at = now
            await self.sessions.save(record)
        return self._to_response(message)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _require_session(self, session_id: str):
        record = await self.sessions.get_by_owner(
            self.user.tenant_id, self.user.user_id, session_id
        )
        if record is None:
            raise BizError(404, f"session {session_id} not found")
        return record

    @staticmethod
    def _extract_text(parts: list[dict]) -> str:
        """从内容块中抽取纯文本（text / tool_result 块）。"""
        chunks: list[str] = []
        for part in parts:
            value = part.get("text") if isinstance(part, dict) else None
            if value:
                chunks.append(str(value))
        return "\n".join(chunks)

    @staticmethod
    def _to_response(record: SessionMessage) -> MessageResponse:
        """parts 在 PG 为 JSONB、SQLite 为 JSON，正常读出已是列表。"""
        raw = record.parts
        if isinstance(raw, str):
            try:
                raw = json.loads(raw or "[]")
            except (TypeError, ValueError):
                raw = []
        return MessageResponse(
            id=record.id,
            session_id=record.session_id,
            role=record.role,
            parts=raw if isinstance(raw, list) else [],
            text=record.text,
            seq=record.seq,
            parent_id=record.parent_id,
            status=record.status,
            created_at=record.created_at,
        )


__all__ = ["MessageService"]
