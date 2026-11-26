"""消息派生操作 — 失败消息重试与会话分支。

职责边界：
    - ``retry``：把失败 / 取消的 assistant 消息与其对应的 user 消息软删，
      返回原文供前端重新走 SSE，避免重复用户消息与脏占位；
    - ``branch``：以指定消息为分界，把历史消息复制到新会话（新 id / seq），
      用 ``parent_id`` 标记来源。

不负责会话 CRUD，也不直接触达 Agent。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from harness.platform.api.exceptions import BizError
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.message_vo import (
    MessageBranchResponse,
    MessageRetryResponse,
)
from harness.platform.entity.session import SessionRecord
from harness.platform.entity.session_message import SessionMessage
from harness.platform.repository.session_message_repository import (
    SessionMessageRepository,
)
from harness.platform.repository.session_repository import SessionRepository

# 允许重试的消息终态
_RETRYABLE = frozenset({"failed", "cancelled"})

# 分支标题后缀与长度上限（sessions.title 最长 256）
_BRANCH_SUFFIX = " · 分支"
_TITLE_LIMIT = 256


class MessageActionService:
    """从历史消息派生新动作（重试 / 分支）的用例。"""

    def __init__(self, user: UserInfo, db) -> None:
        self.user = user
        self.db = db
        self.messages = SessionMessageRepository(db)
        self.sessions = SessionRepository(db)

    async def retry(self, session_id: str, message_id: str) -> MessageRetryResponse:
        """重试失败 / 取消的助手消息：软删旧的一问一答，返回用户原文。"""
        await self._require_session(session_id)
        target = await self.messages.get_in_session(
            self.user.tenant_id, session_id, message_id
        )
        if target is None:
            raise BizError(404, f"message {message_id} not found")
        if target.role != "assistant" or target.status not in _RETRYABLE:
            raise BizError(409, "only failed or cancelled assistant messages can be retried")
        if await self.messages.has_after(
            self.user.tenant_id, session_id, target.seq
        ):
            raise BizError(409, "only the latest message can be retried")

        source = await self.messages.previous_user(
            self.user.tenant_id, session_id, target.seq
        )
        if source is None:
            raise BizError(409, "no user message found for retry")

        now = datetime.now(timezone.utc)
        for item in (source, target):
            item.deleted_at = now
            await self.messages.save(item)
        await self._refresh_session(session_id, now)

        return MessageRetryResponse(
            session_id=session_id,
            message_id=message_id,
            text=source.text or self._extract_text(source.parts),
            removed_message_ids=[source.id, target.id],
        )

    async def branch(self, session_id: str, message_id: str) -> MessageBranchResponse:
        """以指定消息为分界复制历史到新会话，返回新会话摘要。"""
        source_session = await self._require_session(session_id)
        target = await self.messages.get_in_session(
            self.user.tenant_id, session_id, message_id
        )
        if target is None:
            raise BizError(404, f"message {message_id} not found")
        if target.status == "streaming":
            raise BizError(409, "streaming message cannot be branched")

        now = datetime.now(timezone.utc)
        new_session_id = f"sess-{uuid.uuid4().hex[:12]}"
        title = self._branch_title(source_session.title)
        record = SessionRecord(
            session_id=new_session_id,
            tenant_id=self.user.tenant_id,
            user_id=self.user.user_id,
            title=title,
            created_at=now,
            updated_at=now,
        )
        await self.sessions.save(record)

        origins = await self.messages.list_up_to(
            self.user.tenant_id, session_id, target.seq
        )
        last_at: datetime | None = None
        for seq, origin in enumerate(origins, start=1):
            copy = SessionMessage(
                id=f"msg-{new_session_id}-{seq}",
                session_id=new_session_id,
                tenant_id=self.user.tenant_id,
                user_id=origin.user_id,
                role=origin.role,
                parts=[dict(part) for part in origin.parts],
                text=origin.text,
                seq=seq,
                parent_id=origin.id,
                status=origin.status,
                created_at=origin.created_at,
            )
            await self.messages.save(copy)
            last_at = origin.created_at

        record.message_count = len(origins)
        record.last_message_at = last_at
        record.updated_at = now
        await self.sessions.save(record)

        return MessageBranchResponse(
            session_id=new_session_id,
            source_session_id=session_id,
            source_message_id=message_id,
            title=title,
            message_count=len(origins),
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _require_session(self, session_id: str) -> SessionRecord:
        record = await self.sessions.get_by_owner(
            self.user.tenant_id, self.user.user_id, session_id
        )
        if record is None:
            raise BizError(404, f"session {session_id} not found")
        return record

    async def _refresh_session(self, session_id: str, now: datetime) -> None:
        """重试软删后刷新会话计数与活跃时间。"""
        record = await self.sessions.get_by_owner(
            self.user.tenant_id, self.user.user_id, session_id
        )
        if record is None:
            return
        count = await self.messages.count_by_session(
            self.user.tenant_id, session_id
        )
        record.message_count = count
        record.last_message_at = now if count else None
        record.updated_at = now
        await self.sessions.save(record)

    @staticmethod
    def _branch_title(title: str) -> str:
        """生成分支会话标题，超出列宽时截断。"""
        base = (title or "会话").strip() or "会话"
        return f"{base}{_BRANCH_SUFFIX}"[:_TITLE_LIMIT]

    @staticmethod
    def _extract_text(parts: list[dict]) -> str:
        """从内容块中抽取纯文本（text 块）。"""
        chunks = [str(part.get("text")) for part in parts if part.get("text")]
        return "\n".join(chunks)


__all__ = ["MessageActionService"]
