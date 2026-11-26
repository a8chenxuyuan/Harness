"""审计查询与导出测试（过滤 / 分页 / 权限 / CSV）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from httpx import AsyncClient

AUDIT_PATH = "/api/v1/audit-logs"


async def _owner_headers(client: AsyncClient, register_user, db_session) -> dict:
    """注册用户并提升为 owner，返回可访问审计接口的认证头。"""
    from harness.platform.repository.user_repository import UserRepository
    from harness.platform.service.auth_service import DEFAULT_TENANT_ID

    username, password, _ = await register_user()
    users = UserRepository(db_session)
    user = await users.get_by_username(DEFAULT_TENANT_ID, username)
    user.role = "owner"
    await users.save(user)

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200, login.text
    token = login.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _seed(db_session, **overrides) -> None:
    from harness.platform.auth.audit import record_audit
    from harness.platform.service.auth_service import DEFAULT_TENANT_ID

    payload = {
        "tenant_id": DEFAULT_TENANT_ID,
        "user_id": "u-1",
        "action": "session.create",
        "target": "sess-1",
        "result": "success",
        "session_id": "sess-1",
        "detail": {"source": "test"},
    }
    payload.update(overrides)
    await record_audit(db_session, **payload)


async def test_list_paginates_and_counts(
    client: AsyncClient, register_user, db_session
) -> None:
    """分页返回当前页，total 为过滤后的真实总数。"""
    headers = await _owner_headers(client, register_user, db_session)
    for index in range(5):
        await _seed(db_session, target=f"sess-{index}")

    first = await client.get(
        AUDIT_PATH,
        params={"page": 1, "size": 2, "action": "session.create"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    data = first.json()["data"]
    assert data["total"] == 5
    assert len(data["items"]) == 2

    second = await client.get(
        AUDIT_PATH,
        params={"page": 3, "size": 2, "action": "session.create"},
        headers=headers,
    )
    assert len(second.json()["data"]["items"]) == 1


async def test_filters_action_user_session_result_and_time(
    client: AsyncClient, register_user, db_session
) -> None:
    """动作 / 用户 / 会话 / 结果 / 时间范围过滤均生效。"""
    headers = await _owner_headers(client, register_user, db_session)
    await _seed(db_session, action="auth.login", user_id="u-1", result="success")
    await _seed(db_session, action="agent.run", user_id="u-2", result="error", session_id="sess-2")
    await _seed(db_session, action="agent.run", user_id="u-2", result="success", session_id="sess-2")

    async def total(params: dict) -> int:
        resp = await client.get(AUDIT_PATH, params=params, headers=headers)
        assert resp.status_code == 200, resp.text
        return resp.json()["data"]["total"]

    assert await total({"action": "agent.run"}) == 2
    assert await total({"user_id": "u-1"}) == 1
    assert await total({"session_id": "sess-2"}) == 2
    assert await total({"result": "error"}) == 1
    assert await total({"action": "agent.run", "result": "success"}) == 1

    now = datetime.now(timezone.utc)
    past = (now - timedelta(hours=1)).isoformat()
    future = (now + timedelta(hours=1)).isoformat()
    assert await total({"action": "agent.run", "since": past, "until": future}) == 2
    assert await total({"since": future}) == 0


async def test_actions_and_tenant_isolation(
    client: AsyncClient, register_user, db_session
) -> None:
    """动作枚举去重；跨租户日志不可见。"""
    headers = await _owner_headers(client, register_user, db_session)
    await _seed(db_session, action="session.create")
    await _seed(db_session, action="agent.run")
    await _seed(db_session, action="agent.run")
    await _seed(db_session, tenant_id="other-tenant", action="secret.action")

    actions = await client.get(f"{AUDIT_PATH}/actions", headers=headers)
    values = actions.json()["data"]
    assert {"agent.run", "session.create"}.issubset(set(values))
    assert "secret.action" not in values

    listed = await client.get(
        AUDIT_PATH, params={"action": "session.create"}, headers=headers
    )
    assert listed.json()["data"]["total"] == 1


async def test_export_csv_with_filter(
    client: AsyncClient, register_user, db_session
) -> None:
    """导出 CSV：带 BOM、表头正确、过滤条件生效。"""
    headers = await _owner_headers(client, register_user, db_session)
    await _seed(db_session, action="session.create", target="sess-a")
    await _seed(db_session, action="agent.run", target="sess-b")

    resp = await client.get(f"{AUDIT_PATH}/export?action=agent.run", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]

    text = resp.content.decode("utf-8-sig")
    lines = [line for line in text.splitlines() if line]
    assert lines[0] == "时间,动作,结果,用户,会话,目标,详情"
    assert len(lines) == 2
    assert "agent.run" in lines[1]
    assert "session.create" not in text


async def test_member_forbidden_and_bad_detail(
    client: AsyncClient, auth_headers, register_user, db_session
) -> None:
    """member 无权访问；detail 脏数据不打断查询。"""
    denied = await client.get(AUDIT_PATH, headers=auth_headers)
    assert denied.status_code == 403
    export_denied = await client.get(f"{AUDIT_PATH}/export", headers=auth_headers)
    assert export_denied.status_code == 403

    headers = await _owner_headers(client, register_user, db_session)
    from harness.platform.repository.audit_repository import AuditRepository

    await AuditRepository(db_session).log(
        tenant_id="dev-tenant",
        user_id="u-9",
        action="tool.call",
        detail_json="not-json",
    )
    listed = await client.get(f"{AUDIT_PATH}?action=tool.call", headers=headers)
    assert listed.status_code == 200, listed.text
    item = listed.json()["data"]["items"][0]
    assert item["detail"] == {}
    assert item["created_at"].endswith("Z")
