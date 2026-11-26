"""流式对话测试（SSE 事件序列 / 增量落库 / 断线状态 / 参数校验）。"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from httpx import AsyncClient

from harness.core.loop.streaming import (
    EVENT_ERROR,
    EVENT_FINISH,
    EVENT_TEXT_DELTA,
    EVENT_TOOL_END,
    EVENT_TOOL_START,
    LoopStreamEvent,
)
from harness.platform.service.stream_service import ChatStreamService

STREAM_PATH = "/api/v1/agents/run/stream"
SESSIONS_PATH = "/api/v1/sessions"


class _FakeAgent:
    """替身 Agent：按预设事件序列流式产出，不触达真实模型。"""

    def __init__(self, events: list[LoopStreamEvent], metrics: dict | None = None):
        self._events = events
        self.state = (
            SimpleNamespace(metrics=metrics)
            if metrics is not None
            else None
        )

    async def run_stream(self, user_input: str, **kwargs):
        for event in self._events:
            await asyncio.sleep(0)
            yield event


def _patch_agent(monkeypatch, events: list[LoopStreamEvent], metrics=None) -> None:
    """把 ChatStreamService 的 Agent 构造替换为替身。"""
    agent = _FakeAgent(events, metrics)
    monkeypatch.setattr(
        ChatStreamService, "_build_agent", staticmethod(lambda run_id: agent)
    )


def _parse_sse(raw: str) -> list[tuple[str, dict]]:
    """把 SSE 文本解析成 [(event, data)]。"""
    parsed: list[tuple[str, dict]] = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        event = "message"
        data = "{}"
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        parsed.append((event, json.loads(data)))
    return parsed


async def _create_session(client: AsyncClient, headers: dict) -> str:
    resp = await client.post(SESSIONS_PATH, json={"title": "流式测试"}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["session_id"]


def _happy_events() -> list[LoopStreamEvent]:
    """一段完整对话：文本 → 工具调用 → 继续文本。"""
    return [
        LoopStreamEvent(EVENT_TEXT_DELTA, {"delta": "你好"}),
        LoopStreamEvent(EVENT_TEXT_DELTA, {"delta": "，世界"}),
        LoopStreamEvent(EVENT_FINISH, {"text": "你好，世界", "step": 0}),
        LoopStreamEvent(
            EVENT_TOOL_START,
            {
                "tool_count": 1,
                "step": 0,
                "calls": [
                    {"id": "t1", "name": "read_file", "arguments": {"path": "a.txt"}}
                ],
            },
        ),
        LoopStreamEvent(
            EVENT_TOOL_END,
            {
                "tool_count": 1,
                "step": 0,
                "results": [
                    {
                        "id": "t1",
                        "name": "read_file",
                        "arguments": {"path": "a.txt"},
                        "ok": True,
                        "output": "hello",
                        "error": None,
                        "execution_time_ms": 2.0,
                    }
                ],
            },
        ),
        LoopStreamEvent(EVENT_TEXT_DELTA, {"delta": "完成"}),
        LoopStreamEvent(EVENT_FINISH, {"text": "完成", "step": 1}),
    ]


async def test_stream_success_persists_incremental_message(
    client: AsyncClient, auth_headers, monkeypatch
) -> None:
    """流式成功后：事件完整、消息 completed、内容块含工具调用。"""
    _patch_agent(
        monkeypatch,
        _happy_events(),
        {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )
    session_id = await _create_session(client, auth_headers)

    async with client.stream(
        "POST",
        STREAM_PATH,
        json={"goal": "你好", "mode": "single", "conversation_id": session_id},
        headers=auth_headers,
    ) as resp:
        assert resp.status_code == 200, await resp.aread()
        raw = (await resp.aread()).decode("utf-8")

    events = _parse_sse(raw)
    names = [name for name, _ in events]
    assert names[0] == "message_start"
    assert names[-1] == "message_end"
    assert names.count("part_delta") == 3
    assert names.count("tool_call") == 2
    assert events[0][1]["seq"] == 2

    end = events[-1][1]
    assert end["status"] == "completed"
    assert end["metrics"]["total_tokens"] == 15
    assert end["message"]["text"] == "你好，世界完成"
    assert [part["type"] for part in end["message"]["parts"]] == [
        "text",
        "tool_call",
        "text",
    ]
    assert end["message"]["parts"][1]["name"] == "read_file"
    assert end["message"]["parts"][1]["content"] == "hello"

    listed = await client.get(
        f"{SESSIONS_PATH}/{session_id}/messages", headers=auth_headers
    )
    items = listed.json()["data"]["items"]
    assert [item["role"] for item in items] == ["user", "assistant"]
    assert items[1]["status"] == "completed"
    assert items[1]["text"] == "你好，世界完成"
    assert items[1]["parts"][1]["ok"] is True


async def test_stream_model_error_marks_failed(
    client: AsyncClient, auth_headers, monkeypatch
) -> None:
    """模型报错：消息与运行记录都置 failed，并推送 error 事件。"""
    _patch_agent(
        monkeypatch,
        [
            LoopStreamEvent(EVENT_TEXT_DELTA, {"delta": "半截"}),
            LoopStreamEvent(EVENT_ERROR, {"error": "模型超时"}),
        ],
    )
    session_id = await _create_session(client, auth_headers)

    async with client.stream(
        "POST",
        STREAM_PATH,
        json={"goal": "报错", "mode": "single", "conversation_id": session_id},
        headers=auth_headers,
    ) as resp:
        assert resp.status_code == 200
        raw = (await resp.aread()).decode("utf-8")

    events = _parse_sse(raw)
    by_name = dict(events)
    assert by_name["error"]["message"] == "模型超时"
    assert by_name["message_end"]["status"] == "failed"
    assert by_name["message_end"]["error"] == "模型超时"

    items = (
        await client.get(
            f"{SESSIONS_PATH}/{session_id}/messages", headers=auth_headers
        )
    ).json()["data"]["items"]
    assert items[-1]["status"] == "failed"
    assert items[-1]["text"] == "半截"


async def test_stream_disconnect_marks_failed(
    db_session, user_info, monkeypatch
) -> None:
    """客户端中途断开：已生成内容保留，消息置 failed。"""
    from harness.platform.repository.session_message_repository import (
        SessionMessageRepository,
    )
    from harness.platform.service.session_service import SessionService

    _patch_agent(monkeypatch, _happy_events())
    session = await SessionService(user_info, db_session).create_session("断线")
    service = ChatStreamService(user_info, db_session)

    agen = service.stream(session.session_id, "问题")
    first = await agen.__anext__()
    assert first.event == "message_start"
    second = await agen.__anext__()
    assert second.event == "part_delta"
    await agen.aclose()

    messages = await SessionMessageRepository(db_session).list_by_session(
        user_info.tenant_id, session.session_id
    )
    assert [item.role for item in messages] == ["user", "assistant"]
    assert messages[-1].status == "failed"
    assert messages[-1].text == "你好"


async def test_stream_requires_owned_session(
    client: AsyncClient, auth_headers, register_user, monkeypatch
) -> None:
    """缺少 conversation_id / 越权会话 / 非 single 模式均被拒绝。"""
    _patch_agent(monkeypatch, _happy_events())

    missing = await client.post(
        STREAM_PATH, json={"goal": "x", "mode": "single"}, headers=auth_headers
    )
    assert missing.status_code == 400

    bad_mode = await client.post(
        STREAM_PATH,
        json={"goal": "x", "mode": "coordinator", "conversation_id": "s-any"},
        headers=auth_headers,
    )
    assert bad_mode.status_code == 400

    session_id = await _create_session(client, auth_headers)
    _, _, data = await register_user()
    other_headers = {"Authorization": f"Bearer {data['access_token']}"}
    denied = await client.post(
        STREAM_PATH,
        json={"goal": "x", "mode": "single", "conversation_id": session_id},
        headers=other_headers,
    )
    assert denied.status_code == 404


async def test_stream_cancel_marks_cancelled(
    db_session, user_info, monkeypatch
) -> None:
    """登记取消后停止生成：已生成内容保留，消息与运行记录都置 cancelled。"""
    from harness.platform.repository.agent_run_repository import AgentRunRepository
    from harness.platform.repository.session_message_repository import (
        SessionMessageRepository,
    )
    from harness.platform.service.session_service import SessionService
    from harness.platform.service.stream_cancel import (
        get_stream_cancel_registry,
        reset_stream_cancel_registry,
    )

    reset_stream_cancel_registry()
    _patch_agent(monkeypatch, _happy_events())
    session = await SessionService(user_info, db_session).create_session("取消")
    service = ChatStreamService(user_info, db_session)

    agen = service.stream(session.session_id, "问题")
    started = await agen.__anext__()
    assert started.event == "message_start"
    run_id = started.data["run_id"]

    # 先推进一个事件，确保 stream 已登记 run_id
    delta = await agen.__anext__()
    assert delta.event == "part_delta"
    assert get_stream_cancel_registry().request(run_id) is True

    events = [event async for event in agen]
    assert events[-1].event == "message_end"
    assert events[-1].data["status"] == "cancelled"
    assert events[-1].data["error"] == "用户取消"

    messages = await SessionMessageRepository(db_session).list_by_session(
        user_info.tenant_id, session.session_id
    )
    assert messages[-1].status == "cancelled"
    assert messages[-1].text == "你好"

    record = await AgentRunRepository(db_session).get(run_id)
    assert record is not None
    assert record.status == "cancelled"

    reset_stream_cancel_registry()


async def test_cancel_endpoint_settles_orphan_run(
    client: AsyncClient, auth_headers, db_session
) -> None:
    """无活跃流的取消请求：运行记录与残留 streaming 消息直接置 cancelled。"""
    from harness.platform.api.vo.auth_vo import UserInfo
    from harness.platform.entity.agent_run import AgentRun
    from harness.platform.repository.agent_run_repository import AgentRunRepository
    from harness.platform.repository.session_message_repository import (
        SessionMessageRepository,
    )
    from harness.platform.service.message_service import MessageService
    from harness.platform.service.session_service import SessionService

    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()["data"]
    user = UserInfo(
        user_id=me["user_id"], tenant_id=me["tenant_id"], role=me["role"]
    )
    session = await SessionService(user, db_session).create_session("取消接口")
    await MessageService(user, db_session).start_streaming_message(session.session_id)
    runs = AgentRunRepository(db_session)
    await runs.save(
        AgentRun(
            run_id="run-orphan-1",
            session_id=session.session_id,
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            mode="single",
            status="running",
        )
    )

    resp = await client.post(
        "/api/v1/agents/runs/run-orphan-1/cancel", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "cancelled"

    db_session.expire_all()
    record = await runs.get("run-orphan-1")
    assert record.status == "cancelled"
    messages = await SessionMessageRepository(db_session).list_by_session(
        user.tenant_id, session.session_id
    )
    assert messages[-1].status == "cancelled"

    missing = await client.post(
        "/api/v1/agents/runs/run-not-exist/cancel", headers=auth_headers
    )
    assert missing.status_code == 404
