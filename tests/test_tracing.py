"""OpenTelemetry 全链路 span 测试（W3-OBS-01）。

sdk 未安装时自动跳过；安装后用 InMemorySpanExporter 断言：
    - HTTP 请求与 agent.run 属于同一个 trace
    - span 自动带上 request_id / tenant_id / run_id
"""

from __future__ import annotations

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from harness.common.observability.tracing import init_otel  # noqa: E402


async def test_http_and_run_spans_share_trace(
    client, auth_headers, monkeypatch
) -> None:
    exporter = InMemorySpanExporter()
    init_otel(service_name="harness-test", exporter=exporter)

    from harness.platform.service.agent_service import AgentService

    async def fake_execute(goal, mode, run_id):  # noqa: ANN001
        return {
            "run_id": run_id,
            "status": "success",
            "output": "ok",
            "metrics": {},
        }

    monkeypatch.setattr(AgentService, "_execute", fake_execute)

    resp = await client.post(
        "/api/v1/agents/run",
        json={"goal": "链路追踪", "mode": "single"},
        headers={**auth_headers, "X-Request-ID": "trace-otel-001"},
    )
    assert resp.status_code == 200, resp.text

    spans = exporter.get_finished_spans()
    by_name = {span.name: span for span in spans}
    assert "http.request" in by_name
    assert "agent.run" in by_name

    http_span = by_name["http.request"]
    run_span = by_name["agent.run"]
    assert http_span.context.trace_id == run_span.context.trace_id

    attrs = dict(run_span.attributes or {})
    assert attrs["request_id"] == "trace-otel-001"
    assert attrs["tenant_id"] == "dev-tenant"
    assert str(attrs["run_id"]).startswith("run-")
    assert attrs["mode"] == "single"

    assert dict(http_span.attributes or {})["http.path"] == "/api/v1/agents/run"
