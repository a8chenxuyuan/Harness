"""指标后端实现：Prometheus 真实现 + 内存 dict 降级实现。

只负责「存储 + 累加」，对外入口统一在 ``metrics.py``。
"""

from __future__ import annotations

from typing import Any


class PromMetricsBackend:
    """用 prometheus-client 做后端。"""

    def __init__(self) -> None:
        from prometheus_client import Counter, Gauge, Histogram

        # 全部 harness_ 前缀，避免撞名
        self.cache_hit_ratio = Gauge(
            "harness_cache_hit_ratio", "Prompt 缓存命中率（0.0-1.0）", ["session_id"]
        )
        self.ttft_seconds = Histogram(
            "harness_ttft_seconds", "首 token 延迟（秒）", ["session_id"]
        )
        self.tool_duration_seconds = Histogram(
            "harness_tool_duration_seconds", "工具调用耗时（秒）", ["tool_name"]
        )
        self.loop_iterations = Counter(
            "harness_loop_iterations", "ReAct 循环总迭代次数", ["session_id"]
        )
        self.compaction_triggered = Counter(
            "harness_compaction_triggered", "触发上下文压缩的次数", ["session_id"]
        )
        self.resume_replayed_tools = Counter(
            "harness_resume_replayed_tools", "resume 时重放的工具调用次数", ["session_id"]
        )
        # --- 编排层（Phase 18） ---
        self.orchestrator_dispatch_total = Counter(
            "harness_orchestrator_dispatch_total", "编排器派发任务次数", ["coordinator_id"],
        )
        self.worker_wall_seconds = Histogram(
            "harness_worker_wall_seconds", "单 Worker 任务墙钟（秒）", ["worker_name"],
        )
        self.worker_cache_hit_ratio = Gauge(
            "harness_worker_cache_hit_ratio", "Worker 缓存命中率", ["worker_name"],
        )
        self.worker_redispatch_total = Counter(
            "harness_worker_redispatch_total", "失败任务重派次数", ["task_id"],
        )
        self.handoff_total = Counter(
            "harness_handoff_total", "handoff 移交次数", ["from_task", "to_worker"],
        )
        self.worker_prefix_stable_rounds = Gauge(
            "harness_worker_prefix_stable_rounds", "Worker 前缀稳定轮次", ["worker_name"],
        )
        # --- Plan / 沙箱 ---
        self.plan_approval_latency = Histogram(
            "harness_plan_approval_latency_seconds", "Plan 闸门等待时长（秒）"
        )
        self.replan_total = Counter(
            "harness_replan_total", "replan 次数", ["plan_id"]
        )
        self.sandbox_violation_total = Counter(
            "harness_sandbox_violation_total", "沙箱越界拦截次数", ["reason"]
        )
        # --- HTTP / 平台（Phase 23） ---
        self.http_requests_total = Counter(
            "harness_http_requests_total", "HTTP 请求数", ["method", "path", "status"]
        )
        self.http_request_duration_seconds = Histogram(
            "harness_http_request_duration_seconds",
            "HTTP 请求耗时（秒）",
            ["method", "path"],
            buckets=(0.01, 0.05, 0.1, 0.3, 0.5, 1.0, 3.0, 10.0, 30.0),
        )
        # --- 模型韧性（W3-KERN-03） ---
        self.model_retry_total = Counter(
            "harness_model_retry_total", "模型调用重试次数", ["model", "reason"]
        )
        self.model_circuit_open_total = Counter(
            "harness_model_circuit_open_total", "模型熔断打开次数", ["model"]
        )
        # --- 限流（W3-PLAT-02） ---
        self.rate_limited_total = Counter(
            "harness_rate_limited_total", "请求被限流次数", ["scope"]
        )

    def record_cache_hit(self, hit: bool, session_id: str) -> None:
        self.cache_hit_ratio.labels(session_id=session_id).set(1.0 if hit else 0.0)

    def record_ttft(self, duration: float, session_id: str) -> None:
        self.ttft_seconds.labels(session_id=session_id).observe(duration)

    def record_tool_duration(self, name: str, duration: float) -> None:
        self.tool_duration_seconds.labels(tool_name=name).observe(duration)

    def record_loop_iteration(self, session_id: str) -> None:
        self.loop_iterations.labels(session_id=session_id).inc()

    def record_compaction(self, session_id: str) -> None:
        self.compaction_triggered.labels(session_id=session_id).inc()

    def record_resume_replay(self, session_id: str, count: int) -> None:
        self.resume_replayed_tools.labels(session_id=session_id).inc(count)

    def record_orchestrator_dispatch(self, count: int, coordinator_id: str) -> None:
        self.orchestrator_dispatch_total.labels(coordinator_id=coordinator_id).inc(count)

    def record_worker_wall_seconds(self, seconds: float, worker_name: str) -> None:
        self.worker_wall_seconds.labels(worker_name=worker_name).observe(seconds)

    def record_worker_cache_hit(self, ratio: float, worker_name: str) -> None:
        self.worker_cache_hit_ratio.labels(worker_name=worker_name).set(ratio)

    def record_worker_redispatch(self, task_id: str, count: int = 1) -> None:
        self.worker_redispatch_total.labels(task_id=task_id).inc(count)

    def record_handoff(self, from_task: str, to_worker: str) -> None:
        self.handoff_total.labels(from_task=from_task, to_worker=to_worker).inc()

    def record_worker_prefix_stable_rounds(self, rounds: int, worker_name: str) -> None:
        self.worker_prefix_stable_rounds.labels(worker_name=worker_name).set(rounds)

    def record_plan_approval_latency(self, seconds: float) -> None:
        self.plan_approval_latency.observe(seconds)

    def record_replan(self, plan_id: str) -> None:
        self.replan_total.labels(plan_id=plan_id).inc()

    def record_sandbox_violation(self, reason: str) -> None:
        self.sandbox_violation_total.labels(reason=reason).inc()

    def record_http_request(
        self, method: str, path: str, status_code: int, duration: float
    ) -> None:
        self.http_requests_total.labels(
            method=method, path=path, status=str(status_code)
        ).inc()
        self.http_request_duration_seconds.labels(
            method=method, path=path
        ).observe(duration)

    def record_model_retry(self, model: str, reason: str) -> None:
        self.model_retry_total.labels(model=model, reason=reason).inc()

    def record_model_circuit_open(self, model: str) -> None:
        self.model_circuit_open_total.labels(model=model).inc()

    def record_rate_limited(self, scope: str) -> None:
        self.rate_limited_total.labels(scope=scope).inc()


class DictMetricsBackend:
    """prometheus-client 没装时的简单内存存储。"""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {
            "cache_hit_ratio": {},
            "ttft_seconds": [],
            "tool_duration_seconds": [],
            "loop_iterations": {},
            "compaction_triggered": {},
            "resume_replayed_tools": {},
            "orchestrator_dispatch_total": {},
            "worker_wall_seconds": [],
            "worker_cache_hit_ratio": {},
            "worker_redispatch_total": {},
            "handoff_total": {},
            "worker_prefix_stable_rounds": {},
            "plan_approval_latency": [],
            "replan_total": {},
            "sandbox_violation_total": {},
            "model_retry_total": {},
            "model_circuit_open_total": {},
            "rate_limited_total": {},
        }

    def record_cache_hit(self, hit: bool, session_id: str) -> None:
        self.data["cache_hit_ratio"][session_id] = 1.0 if hit else 0.0

    def record_ttft(self, duration: float, session_id: str) -> None:
        self.data["ttft_seconds"].append({"session_id": session_id, "value": duration})

    def record_tool_duration(self, name: str, duration: float) -> None:
        self.data["tool_duration_seconds"].append({"tool_name": name, "value": duration})

    def record_loop_iteration(self, session_id: str) -> None:
        key = self.data["loop_iterations"]
        key[session_id] = key.get(session_id, 0) + 1

    def record_compaction(self, session_id: str) -> None:
        key = self.data["compaction_triggered"]
        key[session_id] = key.get(session_id, 0) + 1

    def record_resume_replay(self, session_id: str, count: int) -> None:
        key = self.data["resume_replayed_tools"]
        key[session_id] = key.get(session_id, 0) + count

    def record_orchestrator_dispatch(self, count: int, coordinator_id: str) -> None:
        key = self.data["orchestrator_dispatch_total"]
        key[coordinator_id] = key.get(coordinator_id, 0) + count

    def record_worker_wall_seconds(self, seconds: float, worker_name: str) -> None:
        self.data["worker_wall_seconds"].append(
            {"worker_name": worker_name, "value": seconds}
        )

    def record_worker_cache_hit(self, ratio: float, worker_name: str) -> None:
        self.data["worker_cache_hit_ratio"][worker_name] = ratio

    def record_worker_redispatch(self, task_id: str, count: int = 1) -> None:
        key = self.data["worker_redispatch_total"]
        key[task_id] = key.get(task_id, 0) + count

    def record_handoff(self, from_task: str, to_worker: str) -> None:
        pair = f"{from_task}->{to_worker}"
        key = self.data["handoff_total"]
        key[pair] = key.get(pair, 0) + 1

    def record_worker_prefix_stable_rounds(self, rounds: int, worker_name: str) -> None:
        self.data["worker_prefix_stable_rounds"][worker_name] = rounds

    def record_plan_approval_latency(self, seconds: float) -> None:
        self.data["plan_approval_latency"].append(seconds)

    def record_replan(self, plan_id: str) -> None:
        key = self.data["replan_total"]
        key[plan_id] = key.get(plan_id, 0) + 1

    def record_sandbox_violation(self, reason: str) -> None:
        key = self.data["sandbox_violation_total"]
        key[reason] = key.get(reason, 0) + 1

    def record_model_retry(self, model: str, reason: str) -> None:
        key = self.data["model_retry_total"]
        pair = f"{model}:{reason}"
        key[pair] = key.get(pair, 0) + 1

    def record_model_circuit_open(self, model: str) -> None:
        key = self.data["model_circuit_open_total"]
        key[model] = key.get(model, 0) + 1

    def record_rate_limited(self, scope: str) -> None:
        key = self.data["rate_limited_total"]
        key[scope] = key.get(scope, 0) + 1

    def record_http_request(
        self, method: str, path: str, status_code: int, duration: float
    ) -> None:
        """无 Prometheus 时不重复记明细，摘要统一读 HttpStats。"""
        return None


__all__ = ["DictMetricsBackend", "PromMetricsBackend"]
