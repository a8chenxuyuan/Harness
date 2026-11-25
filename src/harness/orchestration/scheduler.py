"""depends_on 任务图拓扑调度。

唯一职责：把 TaskSpec 列表按依赖关系分成「波次」（wave）——同一波次内
的任务互不依赖，可以安全并行派发；波次之间严格串行。

明确不做：优先级、抢占、动态插入——`depends_on` 拓扑排序对 P18 够用
（见 roadmap 0.4「不自研任务队列中间件」）。
"""

from __future__ import annotations

from collections.abc import Sequence

from .task import TaskSpec


def topo_waves(tasks: Sequence[TaskSpec]) -> list[list[TaskSpec]]:
    """按 depends_on 做 Kahn 分层拓扑排序，产出可并行的波次序列。

    规则：
        1. 同一波次内的任务其依赖全部落在更早的波次里 → 可 asyncio.gather 并行。
        2. 孤立节点（无依赖）统一落在第 0 波。
        3. 依赖不存在的 task_id 或存在环 → 直接抛 ValueError（编排层 fail-fast）。

    Args:
        tasks: 全量任务列表（顺序无关）。

    Returns:
        波次列表，waves[0] 最先派发；空输入返回空列表。

    Raises:
        ValueError: 依赖了不存在的 task_id，或依赖图有环。
    """
    if not tasks:
        return []

    by_id = {t.task_id: t for t in tasks}
    if len(by_id) != len(tasks):
        raise ValueError("存在重复 task_id，任务图非法")

    # 依赖校验：未知依赖 fail-fast
    for t in tasks:
        for dep in t.depends_on:
            if dep not in by_id:
                raise ValueError(f"任务 {t.task_id!r} 依赖了不存在的 {dep!r}")

    # 每个任务剩余的未满足依赖数（Kahn 入度）
    remaining_deps: dict[str, set[str]] = {
        t.task_id: set(t.depends_on) for t in tasks
    }
    scheduled: set[str] = set()
    waves: list[list[TaskSpec]] = []

    while remaining_deps:
        # 本波：所有依赖都已排进前面波次的任务
        ready_ids = [
            tid for tid, deps in remaining_deps.items() if deps <= scheduled
        ]
        if not ready_ids:
            raise ValueError("depends_on 存在环，无法拓扑排序")

        wave = [by_id[tid] for tid in sorted(ready_ids)]
        waves.append(wave)
        scheduled.update(ready_ids)
        for tid in ready_ids:
            remaining_deps.pop(tid)

    return waves
