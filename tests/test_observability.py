"""可观测能力测试：request_id 贯穿 / Prometheus 端点 / 指标摘要。"""

from __future__ import annotations

from httpx import AsyncClient

HEALTH = "/api/v1/health"
SUMMARY = "/api/v1/observability/metrics"


async def test_request_id_echo_and_generate(client: AsyncClient) -> None:
    """客户端传入的 request_id 原样回写；未传时服务端生成。"""
    echoed = await client.get(HEALTH, headers={"X-Request-ID": "trace-abc-001"})
    assert echoed.status_code == 200
    assert echoed.headers["X-Request-ID"] == "trace-abc-001"

    generated = await client.get(HEALTH)
    value = generated.headers["X-Request-ID"]
    assert value.startswith("req-")
    assert len(value) == 20

    missing = await client.get("/api/v1/not-exists")
    assert missing.status_code == 404
    assert missing.headers.get("X-Request-ID")


async def test_request_id_carried_into_audit(
    client: AsyncClient, owner_headers
) -> None:
    """审计 detail 自动带上当前请求的 request_id。"""
    created = await client.post(
        "/api/v1/sessions", json={"title": "链路追踪"}, headers=owner_headers
    )
    session_id = created.json()["data"]["session_id"]

    archived = await client.post(
        f"/api/v1/sessions/{session_id}/archive",
        headers={**owner_headers, "X-Request-ID": "trace-audit-001"},
    )
    assert archived.status_code == 200, archived.text

    listed = await client.get(
        "/api/v1/audit-logs",
        params={"action": "session.archive"},
        headers=owner_headers,
    )
    items = listed.json()["data"]["items"]
    matched = next(item for item in items if item["target"] == session_id)
    assert matched["detail"]["request_id"] == "trace-audit-001"


async def test_prometheus_endpoint(client: AsyncClient) -> None:
    """/metrics 可被 scrape，path 标签使用路由模板。"""
    await client.get(HEALTH, headers={"X-Request-ID": "trace-metrics-001"})
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    text = resp.text
    assert "harness_http_requests_total" in text
    assert 'path="/api/v1/health"' in text
    assert "harness_http_request_duration_seconds" in text


async def test_metrics_summary_permission_and_content(
    client: AsyncClient, auth_headers, owner_headers
) -> None:
    """摘要接口仅 owner/admin 可读，且包含最近错误与 request_id。"""
    denied = await client.get(SUMMARY, headers=auth_headers)
    assert denied.status_code == 403

    await client.get(
        "/api/v1/not-exists", headers={"X-Request-ID": "trace-error-404"}
    )
    resp = await client.get(SUMMARY, headers=owner_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total_requests"] >= 1
    assert 0.0 <= data["error_rate"] <= 1.0
    assert set(data["status_counts"]) == {"ok", "redirect", "client_error", "server_error"}
    assert data["prometheus_available"] is True

    error = data["recent_errors"][0]
    assert error["status"] == 404
    assert error["request_id"] == "trace-error-404"
    assert error["path"] == "/api/v1/not-exists"
