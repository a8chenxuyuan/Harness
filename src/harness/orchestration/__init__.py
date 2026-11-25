"""harness.orchestration —— 多 Agent 编排层（Phase 18-19）。

公共导出：
    - Phase 18: TaskSpec / TaskResult / TaskStatus / WorkerAgent
      CoordinatorAgent / WorkerSpec / ConfigurationError
      topo_waves / HandoffDeclaration / parse_handoff
    - Phase 19: Plan / PlanAgent / PlanExecutor / PlanExecutionResult
      ReplanEntry / ReplanHandler / review_plan
"""

from .coordinator import ConfigurationError, CoordinatorAgent, WorkerSpec
from .executor import PlanExecutionResult, PlanExecutor
from .handoff import HandoffDeclaration, parse_handoff
from .plan import Plan, PlanAgent, ReplanEntry
from .replan import ReplanHandler
from .review import review_plan
from .scheduler import topo_waves
from .task import TaskResult, TaskSpec, TaskStatus
from .worker import WorkerAgent

__all__ = [
    "ConfigurationError",
    "CoordinatorAgent",
    "HandoffDeclaration",
    "Plan",
    "PlanAgent",
    "PlanExecutionResult",
    "PlanExecutor",
    "ReplanEntry",
    "ReplanHandler",
    "TaskResult",
    "TaskSpec",
    "TaskStatus",
    "WorkerAgent",
    "WorkerSpec",
    "parse_handoff",
    "review_plan",
    "topo_waves",
]
