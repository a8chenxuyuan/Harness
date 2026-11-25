"""工具并行调度的准入控制。

plan_batch 是整个 Phase 6 并行能力的核心：给一批 (tool_name, args)
按只读/读写分组，输出一个二维列表——内层 list 可以 asyncio.gather，
外层 list 必须串行。

内置规则：
- 同名工具不可并行（dedup_cache 会命中）
- bash / write_file 与任何写工具互斥
- 只读工具之间可以自由并行（没有副作用）
"""

from __future__ import annotations

from typing import Any

from harness.core.tool.registry import ToolRegistry


class ConflictGroup:
    """把工具名按只读/写分组，并提供冲突判断规则。

    Attributes:
        readonly_tools: 只读工具名集合。
        write_tools: 写工具名集合。
        mutually_exclusive_with_write: 特殊写工具名集合——即使同为写，
            也不能和其他写工具并行（如 bash、write_file）。
    """

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        mutually_exclusive_with_write: set[str] | None = None,
    ) -> None:
        """构造冲突组。

        Args:
            registry: 工具注册表，从中按 readonly 分两组。
            mutually_exclusive_with_write: 额外声明的"最严格"写工具，
                默认包含 {"bash", "write_file"}。
        """
        self.readonly_tools: set[str] = {t.name for t in registry.readonly_tools}
        self.write_tools: set[str] = {t.name for t in registry.write_tools}
        # 内置：bash 和 write_file 不可与任何写工具并行
        default_exclusive = {"bash", "write_file"}
        self.mutually_exclusive_with_write: set[str] = (
            set(mutually_exclusive_with_write) if mutually_exclusive_with_write else default_exclusive
        )

    # --- 规则 -----------------------------------------------------------------

    def can_parallel(self, a: str, b: str) -> bool:
        """判断两个工具是否可以并行执行。

        规则优先级（从高到低）：
        1. 同名 → False（dedup_cache 会命中，直接跳过）
        2. a 或 b 在 exclusive 集合 → False
        3. 两个都是只读 → True
        4. 其他 → False（保守：写工具单独跑）

        Args:
            a: 工具名 A。
            b: 工具名 B。

        Returns:
            True 表示可以同时 gather。
        """
        if a == b:
            return False
        if a in self.mutually_exclusive_with_write or b in self.mutually_exclusive_with_write:
            return False
        a_readonly = a in self.readonly_tools and a not in self.write_tools
        b_readonly = b in self.readonly_tools and b not in self.write_tools
        if a_readonly and b_readonly:
            return True
        return False


def plan_batch(
    calls: list[tuple[str, dict[str, Any]]],
    registry: ToolRegistry,
) -> list[list[tuple[str, dict[str, Any]]]]:
    """把一批 tool_call 按并行友好性切成若干批。

    内层 list 是可以 asyncio.gather 的；外层 list 必须按序 asyncio.gather 之后
    再跑下一批——即批间串行、批内并行。

    算法：贪心——对每个 call，依次尝试塞进已有的某一批（该批内所有 call
    都和它 can_parallel）；塞不进就新开一批。

    Args:
        calls: (tool_name, args_dict) 列表。
        registry: 工具注册表，用于查询 readonly 属性。

    Returns:
        二维列表，外层顺序即执行顺序；内层为 gather 组。
        空输入返回 [[]]（语义上"执行零个 gather"）。
    """
    if not calls:
        return []

    group = ConflictGroup(registry)
    batches: list[list[tuple[str, dict[str, Any]]]] = []

    for name, args in calls:
        placed = False
        for batch in batches:
            # 检查是否与批次里每个已有 call 都兼容
            if all(group.can_parallel(name, existing_name) for existing_name, _ in batch):
                batch.append((name, args))
                placed = True
                break
        if not placed:
            batches.append([(name, args)])

    return batches
