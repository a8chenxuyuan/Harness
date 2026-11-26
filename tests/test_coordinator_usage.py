"""编排层 token 汇总单测（离线，不调用真实模型）。"""

from __future__ import annotations

from harness.orchestration.coordinator import CoordinatorAgent
from harness.orchestration.task import TaskResult, TaskStatus


def test_aggregate_sums_worker_tokens() -> None:
    """Coordinator 聚合要把各 Worker 的 token 累加，失败任务也计入成本。"""
    results = [
        TaskResult(
            task_id="t1",
            status=TaskStatus.DONE,
            output="结果一",
            tokens_used=100,
            prompt_tokens=80,
            completion_tokens=20,
            cache_read_tokens=10,
            wall_seconds=1.0,
        ),
        TaskResult(
            task_id="t2",
            status=TaskStatus.FAILED,
            error="boom",
            tokens_used=50,
            prompt_tokens=40,
            completion_tokens=10,
            wall_seconds=2.0,
        ),
    ]

    aggregated = CoordinatorAgent.aggregate(None, results)  # type: ignore[arg-type]

    assert aggregated["total"] == 2
    assert aggregated["done"] == 1
    assert aggregated["failed"] == 1
    assert aggregated["terminated"] is False
    assert aggregated["prompt_tokens"] == 120
    assert aggregated["completion_tokens"] == 30
    assert aggregated["total_tokens"] == 150
    assert aggregated["cache_read_tokens"] == 10
    assert aggregated["wall_seconds"] == 2.0
