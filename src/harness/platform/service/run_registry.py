"""进程内异步运行注册表（Phase 23）。

用途：``POST /agents/{id}/execute`` 把 Plan 执行放到后台 ``asyncio.Task``，
本注册表负责：
    - 登记 run 状态（pending / running / completed / failed / cancelled）
    - 保存输出与错误
    - 提供取消信号（asyncio.Event + Task.cancel）

限制：进程内内存态，重启即丢。持久化运行队列不在 Phase 23 范围。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Coroutine

log = logging.getLogger(__name__)

_TERMINAL = frozenset({"completed", "failed", "cancelled"})


@dataclass
class RunState:
    """一次后台运行的完整状态。

    Attributes:
        run_id: 运行标识（Phase 23 直接复用 plan_id）。
        status: pending | running | completed | failed | cancelled。
        output: 成功时的文本输出。
        error: 失败原因。
        created_at / finished_at: 时间戳（time.time()）。
        cancel_event: 取消信号（供协作式取消）。
        task: 后台 asyncio.Task 句柄。
    """

    run_id: str
    status: str = "pending"
    output: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: "asyncio.Task[None] | None" = None

    def snapshot(self) -> dict[str, Any]:
        """转成可 JSON 序列化的状态字典。"""
        return {
            "run_id": self.run_id,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class RunRegistry:
    """run_id → RunState 的进程内注册表。"""

    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}

    def create(self, run_id: str) -> RunState:
        """登记一个 run（已存在则复用）。"""
        state = self._runs.get(run_id)
        if state is None:
            state = RunState(run_id=run_id)
            self._runs[run_id] = state
        return state

    def get(self, run_id: str) -> RunState | None:
        """取 run 状态。"""
        return self._runs.get(run_id)

    def status(self, run_id: str) -> dict[str, Any] | None:
        """取 run 状态快照。"""
        state = self._runs.get(run_id)
        return state.snapshot() if state else None

    def start(self, run_id: str, coro: Coroutine[Any, Any, str | None]) -> RunState:
        """把协程放到后台执行，并把结果回填到 RunState。

        Args:
            run_id: 运行标识。
            coro: 后台协程，返回输出文本（None 表示无输出）。

        Returns:
            已置为 running 的 RunState。
        """
        state = self.create(run_id)
        state.status = "running"
        state.error = None
        state.finished_at = None

        async def _wrapper() -> None:
            try:
                output = await coro
                if state.cancel_event.is_set():
                    state.status = "cancelled"
                else:
                    state.status = "completed"
                    state.output = output
            except asyncio.CancelledError:
                state.status = "cancelled"
                log.info("run %s cancelled", run_id)
                raise
            except Exception as exc:  # noqa: BLE001 — 后台异常只记录不抛出
                state.status = "failed"
                state.error = f"{type(exc).__name__}: {exc}"
                log.warning("run %s failed: %s", run_id, exc)
            finally:
                state.finished_at = time.time()

        state.task = asyncio.create_task(_wrapper())
        return state

    def finish(self, run_id: str, status: str, output: str | None = None,
               error: str | None = None) -> None:
        """外部直接标记终态（异常兜底用）。"""
        state = self.create(run_id)
        state.status = status
        state.output = output
        state.error = error
        state.finished_at = time.time()

    def cancel(self, run_id: str) -> bool:
        """请求取消；已是终态返回 False。"""
        state = self._runs.get(run_id)
        if state is None or state.status in _TERMINAL:
            return False
        state.cancel_event.set()
        if state.task is not None and not state.task.done():
            state.task.cancel()
        state.status = "cancelled"
        state.finished_at = time.time()
        return True


_registry: RunRegistry | None = None


def get_run_registry() -> RunRegistry:
    """获取全局运行注册表单例。"""
    global _registry
    if _registry is None:
        _registry = RunRegistry()
    return _registry


def reset_run_registry() -> None:
    """重置单例（仅供测试）。"""
    global _registry
    _registry = None


__all__ = ["RunState", "RunRegistry", "get_run_registry", "reset_run_registry"]
