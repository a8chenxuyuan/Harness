"""运行记录测试（AgentService 落库 / GET /runs 查询）。"""

from __future__ import annotations

from httpx import AsyncClient

from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.repository.agent_run_repository import AgentRunRepository
from harness.platform.service.agent_service import AgentService


def _patch_execute(service: AgentService, output: str, metrics: dict) -> None:
    """替换真实引擎调用，避免测试依赖模型凭据。"""

    async def _fake_execute(goal: str, mode: str, run_id: str) -> dict:
        return {
            "run_id": run_id,
            "status": "success",
            "output": output,
            "metrics": metrics,
        }

    service._execute = _fake_execute  # type: ignore[method-assign]


async def test_agent_run_persisted_without_session(db_session, user_info) -> None:
    """单次运行落 agent_runs：状态 succeeded、输出与 token 用量齐全。"""
    service = AgentService(user_info, db_session)
    _patch_execute(service, "最终回答", {"total_tokens": 42})

    result = await service.run(goal="做个总结", mode="single")

    record = await AgentRunRepository(db_session).get_by_owner(
        user_info.tenant_id, user_info.user_id, result["run_id"]
    )
    assert record is not None
    assert record.status == "succeeded"
    assert record.output == "最终回答"
    assert record.session_id is None
    assert record.started_at is not None
    assert record.finished_at is not None
    assert "42" in record.token_usage


async def test_agent_run_writes_conversation_messages(db_session, user_info) -> None:
    """带 conversation_id 时，用户输入与助手回答都写入 session_messages。"""
    from harness.platform.repository.session_message_repository import (
        SessionMessageRepository,
    )
    from harness.platform.service.session_service import SessionService

    session = await SessionService(user_info, db_session).create_session("对话")

    service = AgentService(user_info, db_session)
    _patch_execute(service, "回答内容", {})
    result = await service.run(
        goal="问题内容", mode="single", conversation_id=session.session_id
    )

    messages = await SessionMessageRepository(db_session).list_by_session(
        user_info.tenant_id, session.session_id
    )
    assert [m.role for m in messages] == ["user", "assistant"]
    assert [m.text for m in messages] == ["问题内容", "回答内容"]
    assert messages[0].parent_id is None
    assert result["status"] == "success"


async def test_list_and_get_runs(client: AsyncClient, auth_headers, db_session) -> None:
    """GET /runs 与 /runs/{id} 可查到当前用户的运行记录。"""
    me = await client.get(
        "/api/v1/auth/me", headers=auth_headers
    )
    payload = me.json()["data"]
    user = UserInfo(
        user_id=payload["user_id"], tenant_id=payload["tenant_id"], role=payload["role"]
    )

    service = AgentService(user, db_session)
    _patch_execute(service, "ok", {})
    result = await service.run(goal="列表测试", mode="single")

    listed = await client.get("/api/v1/runs", headers=auth_headers)
    assert listed.status_code == 200
    data = listed.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["run_id"] == result["run_id"]

    detail = await client.get(f"/api/v1/runs/{result['run_id']}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["status"] == "succeeded"

    missing = await client.get("/api/v1/runs/not-exist", headers=auth_headers)
    assert missing.status_code == 404
