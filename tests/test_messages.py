"""会话消息接口测试（追加 / 游标分页 / 计数维护 / 属主隔离）。"""

from __future__ import annotations

from httpx import AsyncClient

SESSIONS_PATH = "/api/v1/sessions"


async def _create_session(client: AsyncClient, headers: dict) -> str:
    resp = await client.post(SESSIONS_PATH, json={"title": "消息测试"}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["session_id"]


async def test_append_and_list_messages(
    client: AsyncClient, auth_headers
) -> None:
    """追加两条消息后可按 seq 升序读出，会话 message_count 同步刷新。"""
    session_id = await _create_session(client, auth_headers)
    url = f"{SESSIONS_PATH}/{session_id}/messages"

    first = await client.post(url, json={"role": "user", "text": "你好"}, headers=auth_headers)
    assert first.status_code == 200, first.text
    body = first.json()["data"]
    assert body["seq"] == 1
    assert body["parts"] == [{"type": "text", "text": "你好"}]
    assert body["text"] == "你好"

    second = await client.post(
        url,
        json={"role": "assistant", "parts": [{"type": "text", "text": "你好，有什么可以帮你"}]},
        headers=auth_headers,
    )
    assert second.status_code == 200
    assert second.json()["data"]["seq"] == 2

    listed = await client.get(url, headers=auth_headers)
    assert listed.status_code == 200
    data = listed.json()["data"]
    assert [item["seq"] for item in data["items"]] == [1, 2]
    assert data["has_more"] is False
    assert data["next_cursor"] == 2

    detail = await client.get(f"{SESSIONS_PATH}/{session_id}", headers=auth_headers)
    assert detail.json()["data"]["message_count"] == 2


async def test_message_cursor_pagination(client: AsyncClient, auth_headers) -> None:
    """after_seq 游标只返回更晚的消息。"""
    session_id = await _create_session(client, auth_headers)
    url = f"{SESSIONS_PATH}/{session_id}/messages"
    for index in range(3):
        resp = await client.post(
            url, json={"role": "user", "text": f"msg-{index}"}, headers=auth_headers
        )
        assert resp.status_code == 200

    resp = await client.get(f"{url}?after_seq=1&limit=5", headers=auth_headers)
    data = resp.json()["data"]
    assert [item["seq"] for item in data["items"]] == [2, 3]


async def test_messages_not_visible_to_other_user(
    client: AsyncClient, auth_headers, register_user
) -> None:
    """同租户其他用户读写他人会话消息均 404。"""
    session_id = await _create_session(client, auth_headers)
    _, _, data = await register_user()
    other_headers = {"Authorization": f"Bearer {data['access_token']}"}
    url = f"{SESSIONS_PATH}/{session_id}/messages"

    read = await client.get(url, headers=other_headers)
    assert read.status_code == 404

    write = await client.post(
        url, json={"role": "user", "text": "越权"}, headers=other_headers
    )
    assert write.status_code == 404
