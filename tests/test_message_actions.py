"""消息派生操作测试（失败重试 / 会话分支 / 属主隔离）。"""

from __future__ import annotations

from httpx import AsyncClient

SESSIONS_PATH = "/api/v1/sessions"


async def _create_session(client: AsyncClient, headers: dict) -> str:
    resp = await client.post(SESSIONS_PATH, json={"title": "派生测试"}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["session_id"]


async def _append(
    client: AsyncClient,
    headers: dict,
    session_id: str,
    role: str,
    text: str,
    status: str = "completed",
) -> dict:
    resp = await client.post(
        f"{SESSIONS_PATH}/{session_id}/messages",
        json={"role": role, "text": text, "status": status},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def test_retry_failed_message_soft_deletes_pair(
    client: AsyncClient, auth_headers
) -> None:
    """重试失败助手消息：旧的一问一答软删，返回用户原文。"""
    session_id = await _create_session(client, auth_headers)
    url = f"{SESSIONS_PATH}/{session_id}/messages"
    await _append(client, auth_headers, session_id, "user", "原始问题")
    failed = await _append(client, auth_headers, session_id, "assistant", "半截", "failed")

    resp = await client.post(f"{url}/{failed['id']}/retry", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["text"] == "原始问题"
    assert len(data["removed_message_ids"]) == 2

    listed = await client.get(url, headers=auth_headers)
    assert listed.json()["data"]["items"] == []

    detail = await client.get(f"{SESSIONS_PATH}/{session_id}", headers=auth_headers)
    assert detail.json()["data"]["message_count"] == 0


async def test_retry_rejects_completed_or_non_latest(
    client: AsyncClient, auth_headers
) -> None:
    """只有「最后一条且处于 failed/cancelled」的助手消息可重试。"""
    session_id = await _create_session(client, auth_headers)
    url = f"{SESSIONS_PATH}/{session_id}/messages"

    await _append(client, auth_headers, session_id, "user", "问题一")
    done = await _append(client, auth_headers, session_id, "assistant", "完成")
    completed = await client.post(f"{url}/{done['id']}/retry", headers=auth_headers)
    assert completed.status_code == 409

    failed = await _append(client, auth_headers, session_id, "assistant", "失败", "failed")
    await _append(client, auth_headers, session_id, "user", "后续问题")
    stale = await client.post(f"{url}/{failed['id']}/retry", headers=auth_headers)
    assert stale.status_code == 409


async def test_branch_copies_history_to_new_session(
    client: AsyncClient, auth_headers
) -> None:
    """以指定消息为分界复制历史，新会话使用新 id / seq 并记录来源。"""
    session_id = await _create_session(client, auth_headers)
    url = f"{SESSIONS_PATH}/{session_id}/messages"
    first_user = await _append(client, auth_headers, session_id, "user", "问题一")
    first_answer = await _append(client, auth_headers, session_id, "assistant", "回答一")
    await _append(client, auth_headers, session_id, "user", "问题二")
    await _append(client, auth_headers, session_id, "assistant", "回答二")

    resp = await client.post(f"{url}/{first_answer['id']}/branch", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["source_session_id"] == session_id
    assert data["source_message_id"] == first_answer["id"]
    assert data["message_count"] == 2
    assert data["title"].endswith("· 分支")

    copied = (
        await client.get(
            f"{SESSIONS_PATH}/{data['session_id']}/messages", headers=auth_headers
        )
    ).json()["data"]["items"]
    assert [item["role"] for item in copied] == ["user", "assistant"]
    assert [item["seq"] for item in copied] == [1, 2]
    assert copied[0]["parent_id"] == first_user["id"]
    assert copied[1]["parent_id"] == first_answer["id"]
    assert copied[0]["id"].startswith(f"msg-{data['session_id']}-")

    detail = await client.get(
        f"{SESSIONS_PATH}/{data['session_id']}", headers=auth_headers
    )
    assert detail.json()["data"]["message_count"] == 2


async def test_actions_hidden_from_other_user(
    client: AsyncClient, auth_headers, register_user
) -> None:
    """同租户其他用户对他人消息执行重试 / 分支均 404。"""
    session_id = await _create_session(client, auth_headers)
    url = f"{SESSIONS_PATH}/{session_id}/messages"
    await _append(client, auth_headers, session_id, "user", "问题")
    failed = await _append(client, auth_headers, session_id, "assistant", "失败", "failed")

    _, _, data = await register_user()
    other_headers = {"Authorization": f"Bearer {data['access_token']}"}
    retry = await client.post(
        f"{url}/{failed['id']}/retry", headers=other_headers
    )
    assert retry.status_code == 404
    branch = await client.post(
        f"{url}/{failed['id']}/branch", headers=other_headers
    )
    assert branch.status_code == 404
