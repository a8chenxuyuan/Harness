"""会话运营能力测试（标题自动生成 / 归档与状态过滤）。"""

from __future__ import annotations

from httpx import AsyncClient

SESSIONS_PATH = "/api/v1/sessions"


async def _create(client: AsyncClient, headers: dict, title: str = "") -> dict:
    resp = await client.post(
        SESSIONS_PATH, json={"title": title}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def _append_user(
    client: AsyncClient, headers: dict, session_id: str, text: str
) -> None:
    resp = await client.post(
        f"{SESSIONS_PATH}/{session_id}/messages",
        json={"role": "user", "text": text},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


async def test_first_user_message_generates_title(
    client: AsyncClient, auth_headers
) -> None:
    """占位标题在首条用户消息写入后自动替换，后续消息不再改写。"""
    session = await _create(client, auth_headers, "新会话 2026-11-26 10:00")
    await _append_user(
        client, auth_headers, session["session_id"], "  帮我\n分析  订单超时原因  "
    )

    detail = await client.get(
        f"{SESSIONS_PATH}/{session['session_id']}", headers=auth_headers
    )
    assert detail.json()["data"]["title"] == "帮我 分析 订单超时原因"

    await _append_user(client, auth_headers, session["session_id"], "第二个问题")
    detail = await client.get(
        f"{SESSIONS_PATH}/{session['session_id']}", headers=auth_headers
    )
    assert detail.json()["data"]["title"] == "帮我 分析 订单超时原因"


async def test_custom_title_is_not_overwritten(
    client: AsyncClient, auth_headers
) -> None:
    """用户自定义标题不会被自动生成覆盖。"""
    session = await _create(client, auth_headers, "自定义标题")
    await _append_user(client, auth_headers, session["session_id"], "随便聊聊")

    detail = await client.get(
        f"{SESSIONS_PATH}/{session['session_id']}", headers=auth_headers
    )
    assert detail.json()["data"]["title"] == "自定义标题"


async def test_long_title_is_truncated(client: AsyncClient, auth_headers) -> None:
    """超长首条消息截断为 30 字并追加省略号。"""
    session = await _create(client, auth_headers, "")
    await _append_user(client, auth_headers, session["session_id"], "很长的需求" * 20)

    detail = await client.get(
        f"{SESSIONS_PATH}/{session['session_id']}", headers=auth_headers
    )
    title = detail.json()["data"]["title"]
    assert title.endswith("…")
    assert len(title) == 31


async def test_archive_and_status_filter(
    client: AsyncClient, auth_headers
) -> None:
    """归档后仅出现在 archived 过滤结果，恢复后回到 active。"""
    first = await _create(client, auth_headers, "待归档")
    second = await _create(client, auth_headers, "保持活跃")

    archived = await client.post(
        f"{SESSIONS_PATH}/{first['session_id']}/archive", headers=auth_headers
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["data"]["status"] == "archived"

    archived_list = await client.get(
        f"{SESSIONS_PATH}?status=archived", headers=auth_headers
    )
    data = archived_list.json()["data"]
    assert data["total"] == 1
    assert [item["session_id"] for item in data["items"]] == [first["session_id"]]

    active_list = await client.get(
        f"{SESSIONS_PATH}?status=active", headers=auth_headers
    )
    data = active_list.json()["data"]
    assert data["total"] == 1
    assert [item["session_id"] for item in data["items"]] == [second["session_id"]]

    all_list = await client.get(f"{SESSIONS_PATH}?status=all", headers=auth_headers)
    assert all_list.json()["data"]["total"] == 2

    restored = await client.post(
        f"{SESSIONS_PATH}/{first['session_id']}/unarchive", headers=auth_headers
    )
    assert restored.json()["data"]["status"] == "active"
    assert (
        await client.get(f"{SESSIONS_PATH}?status=archived", headers=auth_headers)
    ).json()["data"]["total"] == 0


async def test_archive_isolated_and_validated(
    client: AsyncClient, auth_headers, register_user
) -> None:
    """他人会话归档 404；非法状态过滤 422。"""
    session = await _create(client, auth_headers, "私有会话")
    _, _, data = await register_user()
    other_headers = {"Authorization": f"Bearer {data['access_token']}"}

    denied = await client.post(
        f"{SESSIONS_PATH}/{session['session_id']}/archive", headers=other_headers
    )
    assert denied.status_code == 404

    invalid = await client.get(
        f"{SESSIONS_PATH}?status=deleted", headers=auth_headers
    )
    assert invalid.status_code == 422
