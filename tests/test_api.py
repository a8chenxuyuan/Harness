"""平台接口集成测试（健康检查 / 会话 CRUD / 用户隔离）。"""

from __future__ import annotations

from httpx import AsyncClient

SESSIONS_PATH = "/api/v1/sessions"


async def test_health(client: AsyncClient) -> None:
    """健康检查返回统一响应结构。"""
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["status"] == "ok"


async def test_sessions_require_auth(client: AsyncClient) -> None:
    """未认证访问会话列表返回 401。"""
    resp = await client.get(SESSIONS_PATH)
    assert resp.status_code == 401


async def test_session_crud_flow(client: AsyncClient, auth_headers) -> None:
    """创建 → 列表 → 详情 → 删除 → 再次查询 404。"""
    created = await client.post(
        SESSIONS_PATH, json={"title": "测试会话", "metadata": {"k": "v"}},
        headers=auth_headers,
    )
    assert created.status_code == 200
    session = created.json()["data"]
    session_id = session["session_id"]
    assert session["title"] == "测试会话"
    assert session["status"] == "active"

    listed = await client.get(SESSIONS_PATH, headers=auth_headers)
    assert listed.status_code == 200
    listing = listed.json()["data"]
    assert listing["total"] == 1
    assert [item["session_id"] for item in listing["items"]] == [session_id]

    detail = await client.get(f"{SESSIONS_PATH}/{session_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["session_id"] == session_id

    deleted = await client.delete(
        f"{SESSIONS_PATH}/{session_id}", headers=auth_headers
    )
    assert deleted.status_code == 200

    missing = await client.get(f"{SESSIONS_PATH}/{session_id}", headers=auth_headers)
    assert missing.status_code == 404


async def test_session_not_visible_to_other_user(
    client: AsyncClient, auth_headers, register_user
) -> None:
    """同租户的其他用户查不到别人的会话。"""
    created = await client.post(
        SESSIONS_PATH, json={"title": "私有会话"}, headers=auth_headers
    )
    session_id = created.json()["data"]["session_id"]

    _, _, data = await register_user()
    other_headers = {"Authorization": f"Bearer {data['access_token']}"}

    detail = await client.get(f"{SESSIONS_PATH}/{session_id}", headers=other_headers)
    assert detail.status_code == 404

    listed = await client.get(SESSIONS_PATH, headers=other_headers)
    assert listed.json()["data"]["total"] == 0
