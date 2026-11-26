"""运行记录应用服务 — 查询 agent_runs（写入由 AgentService 负责）。"""

from __future__ import annotations

import json
from typing import Any

from harness.platform.api.exceptions import BizError
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.run_vo import RunListResponse, RunResponse
from harness.platform.entity.agent_run import AgentRun
from harness.platform.repository.agent_run_repository import AgentRunRepository


class RunService:
    """运行记录查询用例（租户 + 发起人隔离）。"""

    def __init__(self, user: UserInfo, db) -> None:
        self.user = user
        self.repo = AgentRunRepository(db)

    async def list_runs(
        self, *, page: int = 1, size: int = 20, status: str | None = None
    ) -> RunListResponse:
        """分页列出当前用户的运行记录（创建时间倒序）。"""
        offset = (page - 1) * size
        records = await self.repo.list_by_user(
            self.user.tenant_id,
            self.user.user_id,
            offset=offset,
            limit=size,
            status=status,
        )
        total = await self.repo.count_by_user(
            self.user.tenant_id, self.user.user_id, status=status
        )
        return RunListResponse(
            items=[self._to_response(r) for r in records],
            total=total,
            page=page,
            size=size,
        )

    async def get_run(self, run_id: str) -> RunResponse:
        """按 run_id 查询；不存在或不属于当前用户时 404。"""
        record = await self.repo.get_by_owner(
            self.user.tenant_id, self.user.user_id, run_id
        )
        if record is None:
            raise BizError(404, f"run {run_id} not found")
        return self._to_response(record)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @classmethod
    def _to_response(cls, record: AgentRun) -> RunResponse:
        return RunResponse(
            run_id=record.run_id,
            session_id=record.session_id,
            mode=record.mode,
            status=record.status,
            input=cls._load_json(record.input),
            output=record.output,
            error=record.error,
            token_usage=cls._load_json(record.token_usage),
            started_at=record.started_at,
            finished_at=record.finished_at,
            created_at=record.created_at,
        )

    @staticmethod
    def _load_json(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}


__all__ = ["RunService"]
