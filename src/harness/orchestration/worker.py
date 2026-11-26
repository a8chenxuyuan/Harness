"""WorkerAgent：编排层的隔离执行单元。

设计铁律（roadmap 0.3）：
    - 编排层不重写执行：Worker 内部跑的就是第一层 `loop.react_graph.run_loop`。
    - Worker 完全隔离：独立 AgentState + 独立 ContextAssembler + 独立 session_id，
      只回传 TaskResult 摘要，不共享上下文；异常一律转 FAILED 不外抛。

前缀缓存：ContextAssembler 构造期用「Worker 专属 system_prompt + 工具 schema」
定型稳定前缀——多个 Worker 前缀互不相同、各自独立命中缓存。
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from .task import TaskResult, TaskSpec, TaskStatus

if TYPE_CHECKING:
    from harness.core.context.assembler import ContextAssembler
    from harness.core.loop.state import AgentState
    from harness.core.memory.base import Memory
    from harness.core.model.base import Model
    from harness.core.permission.engine import PermissionEngine
    from harness.core.session.checkpoint import CheckpointManager
    from harness.core.tool.registry import ToolRegistry

log = logging.getLogger(__name__)


class WorkerAgent:
    """被 Coordinator 派发的隔离子 Agent（session_id=worker-{name}，独立前缀缓存）。"""

    def __init__(
        self,
        *,
        name: str,
        model: "Model",
        tools: "ToolRegistry",
        system_prompt: str,
        permission_engine: "PermissionEngine | None" = None,
        assembler: "ContextAssembler | None" = None,
        memory: "Memory | None" = None,
        checkpoint: "CheckpointManager | None" = None,
        max_steps: int = 20,
    ) -> None:
        """构造 Worker 并立即定型独立稳定前缀。

        Args:
            name: Worker 名。
            model: 共享的模型实例（模型本身无会话状态，可共享）。
            tools: Worker 可用的工具注册表（应已是 Coordinator 的子集）。
            system_prompt: Worker 专属系统提示（决定其前缀与角色）。
            permission_engine: Worker 自己的权限引擎（模式须由 Coordinator 校验）。
            assembler: 可注入的装配器；None 则按 system_prompt + tools 新建。
            memory: 可选记忆；任务结束后写入结果摘要。
            checkpoint: 可选 checkpoint；注入则 execute 结束时保存。
            max_steps: 默认轮次上限（可被 TaskSpec.max_steps 覆盖）。
        """
        from harness.core.context.assembler import ContextAssembler

        self.name = name
        self.session_id = f"worker-{name}"
        self.model = model
        self.tools = tools
        self.permission_engine = permission_engine
        self.memory = memory
        self.checkpoint = checkpoint
        self.max_steps = max_steps
        self._system_prompt = system_prompt
        # 独立装配器：前缀 = Worker 专属提示 + Worker 工具 schema，构造期定型
        # 上下文窗口跟随模型的真实能力（如 DeepSeek V4 为 1M），不再固定 32k
        self.assembler = assembler or ContextAssembler(
            system_prompt=system_prompt,
            tool_schemas=tools.list_for_llm(),
            max_context_tokens=model.capabilities.max_context_tokens,
        )

    @property
    def prefix_hash(self) -> str:
        """本 Worker 的稳定前缀哈希（与其他 Worker 天然不同）。"""
        return self.assembler.prefix_hash

    # --- 主入口 -------------------------------------------------------------

    async def execute(self, task: TaskSpec) -> TaskResult:
        """执行一个任务：独立 state → run_loop → TaskResult（异常转 FAILED 不外抛）。"""
        from harness.core.loop.react_graph import run_loop
        from harness.core.loop.state import AgentState
        from harness.common.message.helpers import system_message, user_message
        from harness.core.tool.budget import ToolBudget

        start = time.monotonic()
        state = AgentState(
            session_id=self.session_id,
            max_steps=task.max_steps or self.max_steps,
        )
        state.messages.append(system_message(self._system_prompt))
        state.messages.append(user_message(_compose_user_text(task)))

        try:
            registry = _restrict_registry(self.tools, task.tools_allowed)
            await run_loop(
                state,
                self.model,
                registry,
                assembler=self.assembler,
                budget=ToolBudget(),
            )
        except Exception as exc:  # noqa: BLE001 - 异常统一转 FAILED，不外抛
            log.warning("worker %s 任务 %s 执行异常: %s", self.name, task.task_id, exc)
            return TaskResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
                wall_seconds=time.monotonic() - start,
            )

        # streaming 层已吞掉工具异常（ToolResult.ok=False 不冒泡）。
        # 仅当「有工具错误且模型没给出任何最终回答」才判失败；
        # 模型已经根据错误信息恢复并作答时，按 D1.3 的约定不拖垮整轮。
        if _has_tool_errors(state) and not _final_text(state).strip():
            tool_msg = state.tool_results[-1] if state.tool_results else None
            err_text = (tool_msg.content[0].content if tool_msg else "unknown")  # ToolResultBlock.content 是 error 文本
            result = TaskResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                error=f"工具执行失败: {err_text}",
                tokens_used=state.token_usage.total_tokens,
                prompt_tokens=state.token_usage.prompt_tokens,
                completion_tokens=state.token_usage.completion_tokens,
                cache_read_tokens=state.token_usage.cache_read_tokens,
                wall_seconds=time.monotonic() - start,
                rounds=state.step,
                prefix_hash=self.prefix_hash,
            )
            await self._aftermath(task, result, state)
            return result

        result = self._build_result(task, state, time.monotonic() - start)
        await self._aftermath(task, result, state)
        return result

    # --- 内部辅助 ------------------------------------------------------------

    def _build_result(
        self, task: TaskSpec, state: "AgentState", wall: float
    ) -> TaskResult:
        """从跑完的 state 提取 TaskResult 并记编排指标。"""
        from harness.common.observability.metrics import (
            record_worker_cache_hit,
            record_worker_prefix_stable_rounds,
            record_worker_wall_seconds,
        )

        rounds = state.step
        # 前缀在构造期定型且会话内不变 → 第 2 轮起每轮都视为缓存命中
        # （与 tests/fake_provider 的判定口径一致：以 ContextAssembler.prefix_hash 为准）
        for _round in range(1, rounds):
            record_worker_cache_hit(1.0, worker_name=self.name)
        record_worker_prefix_stable_rounds(rounds, worker_name=self.name)
        record_worker_wall_seconds(wall, worker_name=self.name)

        from .handoff import parse_handoff

        final_text = _final_text(state)
        declaration = parse_handoff(final_text, task.task_id)

        return TaskResult(
            task_id=task.task_id,
            status=TaskStatus.DONE,
            output=final_text,
            tokens_used=state.token_usage.total_tokens,
            prompt_tokens=state.token_usage.prompt_tokens,
            completion_tokens=state.token_usage.completion_tokens,
            cache_read_tokens=state.token_usage.cache_read_tokens,
            rounds=rounds,
            wall_seconds=wall,
            prefix_hash=self.prefix_hash,
            handoff_to=declaration.to_worker if declaration else None,
            handoff_context=declaration.context if declaration else None,
        )

    async def _aftermath(
        self, task: TaskSpec, result: TaskResult, state: "AgentState"
    ) -> None:
        """任务结束后的收尾：写记忆 + 存 checkpoint（均不阻塞主流程）。"""
        if self.memory is not None and result.output:
            try:
                await self.memory.save(
                    text=f"[{self.name}] {task.task_id}: {result.output[:500]}",
                    metadata={"task_id": task.task_id, "worker": self.name},
                    session_id=self.session_id,
                )
            except Exception:  # noqa: BLE001
                log.debug("worker %s 记忆写入失败", self.name, exc_info=True)
        if self.checkpoint is not None:
            try:
                await self.checkpoint.save(state)
            except Exception:  # noqa: BLE001
                log.debug("worker %s checkpoint 保存失败", self.name, exc_info=True)


# ---------------------------------------------------------------------------
# 模块级纯函数
# ---------------------------------------------------------------------------


def _compose_user_text(task: TaskSpec) -> str:
    """把 goal 与 input 拼成一条 user 消息文本。"""
    if task.input:
        return f"{task.goal}\n\n[任务输入]\n{task.input}"
    return task.goal


def _restrict_registry(
    base: "ToolRegistry", allowed: tuple[str, ...]
) -> "ToolRegistry":
    """按任务白名单从 Worker 注册表里裁剪出子注册表（空白名单 = 全量）。"""
    from harness.core.tool.registry import ToolRegistry

    if not allowed:
        return base
    sub = ToolRegistry()
    for name in allowed:
        if name in base:
            sub.register(base.get(name))
        else:
            log.warning("任务白名单里的工具 %r 不在 Worker 注册表中，已跳过", name)
    return sub


def _final_text(state: "AgentState") -> str:
    """取最后一轮 assistant 的纯文本输出（无则空串）。"""
    from harness.common.message.role import Role

    for msg in reversed(state.messages):
        if msg.role == Role.ASSISTANT:
            return msg.text()
    return ""


def _has_tool_errors(state: "AgentState") -> bool:
    """检查 state.tool_results 中是否存在 is_error=True 的工具结果块。"""
    for msg in state.tool_results:
        for block in msg.content:
            if block.type == "tool_result" and getattr(block, "is_error", False):
                return True
    return False
