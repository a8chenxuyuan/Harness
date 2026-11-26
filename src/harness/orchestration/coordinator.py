"""CoordinatorAgent：拆解 / 并发派发 / 聚合 / 终止判定的中心协调者。

铁律（roadmap 0.3）：编排式 Supervisor（自己不干活）；权限只收紧不放大
（构造期校验 Worker 工具与权限均为子集，违规抛 ConfigurationError）；终止可断言。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from harness.core.permission.mode import PermissionMode

from .scheduler import topo_waves
from .task import TaskResult, TaskSpec, TaskStatus
from .worker import WorkerAgent

if TYPE_CHECKING:
    from harness.core.memory.base import Memory
    from harness.core.model.base import Model
    from harness.core.permission.engine import PermissionEngine
    from harness.core.tool.registry import ToolRegistry

log = logging.getLogger(__name__)


class ConfigurationError(RuntimeError):
    """编排层配置非法（Worker 越权 / 工具越界）。"""


# 权限档位严格度：数值越小越严格；Worker 必须 ≤ Coordinator。
_MODE_STRICTNESS: dict[str, int] = {
    "lockdown": 0, "explore": 1, "default": 2, "agentic": 3, "trusted": 4,
}


class WorkerSpec(BaseModel):
    """Worker 静态声明：name / system_prompt / tools_allowed / permission_mode / max_steps。"""

    model_config = ConfigDict(frozen=True)

    name: str
    system_prompt: str
    tools_allowed: tuple[str, ...] = ()
    permission_mode: "PermissionMode | None" = None
    max_steps: int = 20


class CoordinatorAgent:
    """中心协调者：拆解 → 派发 → 聚合（workers: name → WorkerAgent）。"""

    def __init__(
        self,
        *,
        model: "Model",
        tools: "ToolRegistry",
        permission_engine: "PermissionEngine",
        worker_specs: list[WorkerSpec],
        memory: "Memory | None" = None,
        enable_checkpoints: bool = False,
        max_redispatch: int = 1,
    ) -> None:
        """构造 Coordinator 并在**构造期**完成 Worker 越权校验（越权抛 ConfigurationError）。

        Args:
            model: 共享模型实例（模型无会话状态，可安全共享）。
            tools: Coordinator 工具注册表（Worker 工具必须是其子集）。
            permission_engine: Coordinator 权限引擎（Worker 模式须 ≤ 其严格度）。
            worker_specs: Worker 声明列表。
            memory: 共享记忆（Worker 结果摘要写入）。
            enable_checkpoints: True 时每个 Worker 独立内存级 CheckpointManager（SessionStore 单库单会话）。
            max_redispatch: 失败任务的最大重派次数。
        """
        from harness.core.session.checkpoint import CheckpointManager
        from harness.core.session.store import SessionStore

        self.model = model
        self.session_id = "coordinator"
        self.tools = tools
        self.permission_engine = permission_engine
        self.memory = memory
        self.max_redispatch = max_redispatch
        self.dispatch_total = 0
        self.redispatch_total = 0
        self.handoff_total = 0
        self._rr_index = 0  # 轮询分配游标

        known = set(tool.name for tool in tools)
        coord_strict = _MODE_STRICTNESS[permission_engine.mode.value]
        self.workers: dict[str, WorkerAgent] = {}
        for spec in worker_specs:
            _validate_worker(spec, known, coord_strict, permission_engine.mode)
            checkpoint = (
                CheckpointManager(SessionStore(":memory:")) if enable_checkpoints else None
            )
            self.workers[spec.name] = WorkerAgent(
                name=spec.name,
                model=model,
                tools=_subset_registry(tools, spec.tools_allowed),
                system_prompt=spec.system_prompt,
                permission_engine=permission_engine,
                memory=memory,
                checkpoint=checkpoint,
                max_steps=spec.max_steps,
            )

    # --- 拆解 -----------------------------------------------------------------

    async def decompose(
        self, goal: str, tasks: list[TaskSpec] | None = None
    ) -> list[TaskSpec]:
        """拆解总目标；显式传入 tasks 则跳过 LLM，task_id 缺失自动补 t1..tn；非法 JSON 抛错。"""
        if tasks is not None:
            return _fill_ids(tasks)
        raw = await self._llm_decompose(goal)
        match = re.search(r"[\[{].*[\]}]", raw, re.DOTALL)
        try:
            items = json.loads(match.group(0) if match else raw)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"LLM 拆解结果不是合法 JSON: {raw[:200]}") from exc
        # 模型可能只返回单个对象，也可能把 depends_on 写成数字下标，统一兜底
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            raise ConfigurationError(f"LLM 拆解结果不是数组: {raw[:200]}")
        return _fill_ids([
            TaskSpec(
                task_id=str(it.get("task_id", "")),
                goal=str(it.get("goal", "")),
                input=str(it.get("input", "")),
                worker=str(it["worker"]) if it.get("worker") else None,
                depends_on=tuple(str(d) for d in (it.get("depends_on") or [])),
            )
            for it in items
            if isinstance(it, dict)
        ])

    # --- 派发 + 聚合 ------------------------------------------------------------

    async def dispatch(self, tasks: list[TaskSpec]) -> list[TaskResult]:
        """按拓扑波次并发派发 → 失败重派 → handoff 路由；返回全部终态结果（含 handoff 追加）。"""
        from harness.common.observability.metrics import (
            record_orchestrator_dispatch,
            record_worker_redispatch,
        )

        results: dict[str, TaskResult] = {}
        for wave in topo_waves(tasks):
            record_orchestrator_dispatch(len(wave), coordinator_id=self.session_id)
            self.dispatch_total += len(wave)
            gathered = await asyncio.gather(*(self.execute_single_task(t) for t in wave))
            for res in gathered:
                results[res.task_id] = res

        for task in tasks:  # 失败重派（上限内）
            res = results.get(task.task_id)
            for attempt in range(self.max_redispatch):
                if res is not None and res.status != TaskStatus.FAILED:
                    break
                log.warning("任务 %s 失败，第 %d 次重派", task.task_id, attempt + 1)
                record_worker_redispatch(task.task_id)
                self.redispatch_total += 1
                res = await self.execute_single_task(task)
                results[task.task_id] = res

        return list(results.values()) + await self._route_handoffs(results)

    async def run(self, goal: str, tasks: list[TaskSpec] | None = None) -> dict:
        """编排闭环：decompose → dispatch → aggregate。"""
        return self.aggregate(await self.dispatch(await self.decompose(goal, tasks)))

    def aggregate(self, results: list[TaskResult]) -> dict:
        """聚合终态并给出终止判定（全部 DONE 或存在 FAILED 均为可断言终止）。"""
        done = [r for r in results if r.status == TaskStatus.DONE]
        failed = [r for r in results if r.status == TaskStatus.FAILED]
        return {
            "total": len(results),
            "done": len(done),
            "failed": len(failed),
            "wall_seconds": round(max((r.wall_seconds for r in results), default=0.0), 3),
            "prompt_tokens": sum(r.prompt_tokens for r in results),
            "completion_tokens": sum(r.completion_tokens for r in results),
            "total_tokens": sum(r.tokens_used for r in results),
            "cache_read_tokens": sum(r.cache_read_tokens for r in results),
            "outputs": {r.task_id: r.output for r in results},
            "prefix_hashes": {r.task_id: r.prefix_hash for r in results},
            "terminated": len(failed) == 0,
        }

    # --- 内部辅助 -----------------------------------------------------------------

    async def execute_single_task(self, task: TaskSpec) -> TaskResult:
        """派发单个任务：选定 Worker（task.worker 或轮询）后执行。"""
        worker = self.workers.get(task.worker or "")
        if worker is None:
            if task.worker:
                log.warning("指定 Worker %r 未注册，回退轮询分配", task.worker)
            worker = self._pick_worker()
        return await worker.execute(task)

    def _pick_worker(self) -> WorkerAgent:
        """未指定 Worker 时按注册顺序轮询分配。"""
        names = list(self.workers)
        worker = self.workers[names[self._rr_index % len(names)]]
        self._rr_index += 1
        return worker

    async def _route_handoffs(self, results: dict[str, TaskResult]) -> list[TaskResult]:
        """对声明了 handoff_to 的结果生成追加任务并派发（一次线性，不递归连锁）。"""
        from harness.common.observability.metrics import record_handoff

        extras: list[TaskResult] = []
        for res in list(results.values()):
            if not res.handoff_to:
                continue
            if res.handoff_to not in self.workers:
                log.warning("handoff 目标 %r 未注册，忽略", res.handoff_to)
                continue
            record_handoff(from_task=res.task_id, to_worker=res.handoff_to)
            self.handoff_total += 1
            follow = TaskSpec(
                task_id=f"{res.task_id}-handoff",
                goal=f"接管任务 {res.task_id} 的后续工作并给出结论。",
                input=res.handoff_context or res.output[:500],
                worker=res.handoff_to,
            )
            extras.append(await self.workers[res.handoff_to].execute(follow))
        return extras

    async def _llm_decompose(self, goal: str) -> str:
        """调 LLM 做任务级拆解（任务级 Skill 的未来挂载点）。"""
        from harness.common.message.helpers import system_message, user_message
        from harness.core.model.types import GenerateOptions

        prompt = ("你是任务拆解协调者。把总目标拆成 1-5 个子任务，只输出 JSON 数组，"
                  "每个元素含 task_id/goal/input/worker/depends_on 字段，不要输出其他内容。"
                  "worker 字段固定填 \"worker\"。")
        response = await self.model.generate(
            [system_message(prompt), user_message(goal)], [], GenerateOptions()
        )
        return response.text


# ---------------------------------------------------------------------------
# 模块级纯函数
# ---------------------------------------------------------------------------


def _validate_worker(
    spec: WorkerSpec, known_tools: set[str], coord_strict: int, coord_mode: "PermissionMode"
) -> None:
    """构造期校验：Worker 工具 ⊆ Coordinator 且权限严格度 ≤ Coordinator（越权抛错）。"""
    overflow = set(spec.tools_allowed) - known_tools
    if overflow:
        raise ConfigurationError(
            f"Worker {spec.name!r} 申请了 Coordinator 未放行的工具: {sorted(overflow)}"
        )
    mode = spec.permission_mode or coord_mode
    if _MODE_STRICTNESS[mode.value] > coord_strict:
        raise ConfigurationError(f"Worker {spec.name!r} 权限模式 {mode} 比 Coordinator 放宽")


def _subset_registry(tools: "ToolRegistry", allowed: tuple[str, ...]) -> "ToolRegistry":
    """从 Coordinator 注册表裁出 Worker 子注册表（空白名单 = 全量继承）。"""
    from harness.core.tool.registry import ToolRegistry

    sub = ToolRegistry()
    for name in allowed or tuple(tool.name for tool in tools):
        sub.register(tools.get(name))
    return sub


def _fill_ids(tasks: list[TaskSpec]) -> list[TaskSpec]:
    """补齐缺失的 task_id（t1..tn）。"""
    return [t.model_copy(update={"task_id": t.task_id or f"t{i + 1}"})
            for i, t in enumerate(tasks)]
