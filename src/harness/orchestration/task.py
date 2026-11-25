"""编排层任务模型：TaskSpec / TaskResult。

职责边界：
    只定义「编排层流转的数据契约」，不包含任何执行逻辑。
    TaskSpec 由 Coordinator 拆解产出，Worker 消费；TaskResult 由 Worker
    产出，Coordinator 聚合。两者都是 frozen Pydantic 模型，保证并发下
    不可被意外篡改。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class TaskStatus(str, Enum):
    """单个任务的生命周期状态。

    Attributes:
        PENDING: 已拆解、尚未派发。
        RUNNING: Worker 正在执行。
        DONE: 执行成功，output 有效。
        FAILED: 执行失败，error 给出原因。
    """

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class TaskSpec(BaseModel):
    """一次可派发的任务规格（Coordinator → Worker 的输入契约）。

    Attributes:
        task_id: 任务唯一标识，由 Coordinator 生成（如 "t1"）。
        goal: 任务目标文本，会作为 Worker 的 user 消息核心。
        input: 附加输入（文件路径、上文摘要等），拼进 user 消息。
        tools_allowed: 本任务允许的工具白名单；空 = 继承 Worker 全部工具。
        skill_ids: 本任务绑定的执行级 Skill（P18 占位，P19+ 实装注入）。
        max_steps: Worker 本任务的 ReAct 轮次上限。
        sandbox_policy: 沙箱策略名（P20 实装）；None = 不进沙箱。
        depends_on: 依赖的前置 task_id 列表，决定拓扑波次。
        worker: 指定执行的 Worker 名；None 由 Coordinator 轮询分配。
    """

    model_config = ConfigDict(frozen=True)

    task_id: str
    goal: str
    input: str = ""
    tools_allowed: tuple[str, ...] = ()
    skill_ids: tuple[str, ...] = ()
    max_steps: int = 20
    sandbox_policy: str | None = None
    depends_on: tuple[str, ...] = ()
    worker: str | None = None


class TaskResult(BaseModel):
    """一次任务的执行结果（Worker → Coordinator 的输出契约）。

    Attributes:
        task_id: 对应的 TaskSpec.task_id。
        status: 终态（DONE / FAILED；PENDING/RUNNING 只在中间态出现）。
        output: 最终产出文本（取 Worker 最后一轮 assistant 纯文本）。
        tokens_used: 粗粒度 token 消耗（prompt+completion，无供应商 usage 时为 0）。
        error: 失败原因；成功为 None。
        wall_seconds: 本次执行的墙钟耗时。
        rounds: 实际跑的 ReAct 轮次。
        prefix_hash: 本次执行使用的稳定前缀哈希（用于跨 Worker 隔离验证）。
        handoff_to: 声明移交的目标 Worker 名；None = 不移交。
        handoff_context: 移交给下家的上下文摘要。
    """

    model_config = ConfigDict(frozen=True)

    task_id: str
    status: TaskStatus
    output: str = ""
    tokens_used: int = 0
    error: str | None = None
    wall_seconds: float = 0.0
    rounds: int = 0
    prefix_hash: str = ""
    handoff_to: str | None = None
    handoff_context: str | None = None
