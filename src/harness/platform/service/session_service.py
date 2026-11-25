"""Session 应用服务 — Phase 22 完整实现（真实 DB，无降级）。"""

from __future__ import annotations

import uuid

from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.session_vo import (
    SessionListResponse,
    SessionResponse,
)
from harness.platform.api.exceptions import BizError
from harness.platform.entity.session import SessionRecord
from harness.platform.repository.session_repository import SessionRepository


class SessionService:
    """会话管理的业务编排（租户隔离）。"""

    def __init__(self, user: UserInfo, session) -> None:
        self.user = user
        self.repo = SessionRepository(session)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_session(
        self, title: str = "", metadata: dict | None = None
    ) -> SessionResponse:
        """创建新会话。"""
        record = SessionRecord(
            session_id=f"sess-{uuid.uuid4().hex[:12]}",
            tenant_id=self.user.tenant_id,
            user_id=self.user.user_id,
            title=title,
            metadata_json=str(metadata or {}),
        )
        await self.repo.save(record)
        return self._to_response(record)

    async def get_session(self, session_id: str) -> SessionResponse:
        """获取会话详情（租户 + 属主隔离，别人的会话查不到）。"""
        record = await self.repo.get_by_owner(
            self.user.tenant_id, self.user.user_id, session_id
        )
        if record is None:
            raise BizError(404, f"session {session_id} not found")
        return self._to_response(record)

    async def list_sessions(self, page: int = 1, size: int = 20) -> SessionListResponse:
        """分页列出当前用户的会话（创建时间倒序）。

        Args:
            page: 页码（从 1 开始）。
            size: 每页条数（调用方已限制 1..100）。
        """
        offset = (page - 1) * size
        records = await self.repo.list_by_user(
            self.user.tenant_id, self.user.user_id, offset=offset, limit=size
        )
        total = await self.repo.count_by_user(self.user.tenant_id, self.user.user_id)
        items = [self._to_response(r) for r in records]
        return SessionListResponse(items=items, total=total, page=page, size=size)

    async def delete_session(self, session_id: str) -> None:
        """删除会话（租户 + 属主隔离）。"""
        record = await self.repo.get_by_owner(
            self.user.tenant_id, self.user.user_id, session_id
        )
        if record is None:
            raise BizError(404, f"session {session_id} not found")
        await self.repo.delete(record.session_id)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @staticmethod
    def _to_response(r: SessionRecord) -> SessionResponse:
        return SessionResponse(
            session_id=r.session_id,
            title=r.title,
            status=r.status,
            message_count=r.message_count,
        )
