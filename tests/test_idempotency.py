"""幂等键测试（W3-KERN-02）。

覆盖：
    - 占位 / 处理中冲突 / 成功后同步回放 / 同键不同体冲突
    - 流式场景即使已完成也不回放（交由调用方轮询 run_id）
    - /agents/run 同 key 只真正执行一次
    - /agents/run/stream 重复 key 返回 409 + run_id
"""

from __future__ import annotations

from harness.platform.service.idempotency_service import (
    SCOPE_RUN,
    SCOPE_STREAM,
    IdempotencyService,
    hash_request,
)


async def test_claim_replay_and_conflicts(db_session) -> None:
    """同步场景：处理中冲突、成功回放、不同 body 冲突。"""
    service = IdempotencyService(db_session)
    body = {"goal": "总结", "mode": "single", "conversation_id": None}
    digest = hash_request(body)

    first = await service.claim("t1", SCOPE_RUN, "k-1", digest)
    assert first.record is not None and first.conflict is None

    busy = await service.claim("t1", SCOPE_RUN, "k-1", digest)
    assert busy.conflict == "in_progress"

    await service.complete(first.record, {"run_id": "run-1", "output": "ok"})

    replay = await service.claim("t1", SCOPE_RUN, "k-1", digest)
    assert replay.cached == {"run_id": "run-1", "output": "ok"}

    mismatch = await service.claim(
        "t1", SCOPE_RUN, "k-1", hash_request({"goal": "另一个目标"})
    )
    assert mismatch.conflict == "hash_mismatch"


async def test_stream_claim_never_replays(db_session) -> None:
    """流式场景：已经成功的 key 仍视为冲突（返回 run_id 供轮询）。"""
    service = IdempotencyService(db_session)
    digest = hash_request({"goal": "hi"})

    first = await service.claim("t1", SCOPE_STREAM, "k-2", digest, run_id="run-2")
    await service.complete(first.record, {"run_id": "run-2"})

    again = await service.claim(
        "t1", SCOPE_STREAM, "k-2", digest, replay_completed=False
    )
    assert again.conflict == "in_progress"
    assert again.run_id == "run-2"
    assert again.cached is None


async def test_run_api_replays_same_key(
    client, auth_headers, monkeypatch
) -> None:
    """POST /agents/run 同 key 同 body 只执行一次。"""
    from harness.platform.service.agent_service import AgentService

    calls: list[str] = []

    async def fake_run(self, goal, mode, conversation_id=None):  # noqa: ANN001
        calls.append(goal)
        return {
            "run_id": f"run-{len(calls)}",
            "status": "success",
            "output": "ok",
            "metrics": {},
        }

    monkeypatch.setattr(AgentService, "run", fake_run)
    headers = {**auth_headers, "Idempotency-Key": "api-key-1"}
    body = {"goal": "幂等测试", "mode": "single"}

    first = await client.post("/api/v1/agents/run", json=body, headers=headers)
    second = await client.post("/api/v1/agents/run", json=body, headers=headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["data"] == second.json()["data"]
    assert calls == ["幂等测试"]

    conflict = await client.post(
        "/api/v1/agents/run",
        json={"goal": "不同目标", "mode": "single"},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert len(calls) == 1


async def test_stream_api_returns_conflict_with_run_id(
    client, auth_headers, db_session
) -> None:
    """流式接口重复 key 开流前直接 409，并带上次 run_id。"""
    session_resp = await client.post(
        "/api/v1/sessions", json={"title": "幂等流"}, headers=auth_headers
    )
    assert session_resp.status_code == 200, session_resp.text
    session_id = session_resp.json()["data"]["session_id"]

    body = {"goal": "流式幂等", "mode": "single", "conversation_id": session_id}
    digest = hash_request(body)
    claim = await IdempotencyService(db_session).claim(
        "dev-tenant", SCOPE_STREAM, "stream-key-1", digest, run_id="run-old"
    )
    assert claim.record is not None

    resp = await client.post(
        "/api/v1/agents/run/stream",
        json=body,
        headers={**auth_headers, "Idempotency-Key": "stream-key-1"},
    )
    assert resp.status_code == 409, resp.text
    payload = resp.json()
    assert payload["data"]["run_id"] == "run-old"
