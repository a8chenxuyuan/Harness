"""Sandbox 协议与 SandboxPolicy（Phase 20）。

职责边界：
    - Sandbox 只是一个最小 async 协议（run_cmd + teardown），
      实现层负责路径白名单 / 资源配额 / 网络白名单。
    - SandboxPolicy 是声明式配置（cpu / mem / 时长 / 路径白名单 / 独立临时目录），
      由 Worker 在 TaskSpec.sandbox_policy 字段里引用，Worker 构造沙箱时消费。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SandboxPolicy(BaseModel):
    """一次沙箱隔离的声明式策略。

    Attributes:
        mode: "process"（进程级）或 "docker"（容器级）。
        working_dir: 工作目录；None 则沙箱自动创建独立临时目录。
        path_whitelist: 允许读写的路径前缀；空=仅 working_dir。
        network: 网络策略——"deny"（完全断网）或 "allow"（不拦截）。
        cpu_time_seconds: 进程 CPU 时间上限（秒）；超时直接 kill。
        memory_mb: 进程内存上限（MB）；超额被 OOM killer 或 sandbox 层拦截。
        wall_timeout_seconds: 墙钟超时（秒）；超时 kill，主进程不受影响。
    """

    model_config = ConfigDict(frozen=True)

    mode: Literal["process", "docker"] = "process"
    working_dir: str | None = None
    path_whitelist: tuple[str, ...] = ()
    network: Literal["deny", "allow"] = "deny"
    cpu_time_seconds: float = 10.0
    memory_mb: int = 128
    wall_timeout_seconds: float = 30.0


class Sandbox(ABC):
    """沙箱执行协议。

    具体实现：ProcessSandbox（默认）、DockerSandbox（可选）。
    任意异常都应在 run_cmd 内部被转换为 SandboxViolation，不外抛——
    主进程绝不因沙箱异常被影响。
    """

    @abstractmethod
    async def run_cmd(
        self,
        cmd: list[str],
        *,
        stdin: str | None = None,
        env: dict[str, str] | None = None,
    ) -> "SandboxResult":
        """在沙箱里执行一条命令，返回 SandboxResult（success / stdout / stderr / violation）。"""
        ...

    @abstractmethod
    async def teardown(self) -> None:
        """释放资源（临时目录、子进程等）。幂等——多次调用不会出错。"""
        ...


class SandboxResult(BaseModel):
    """run_cmd 的返回值。

    Attributes:
        success: exit_code == 0 且无 violation 则 True。
        exit_code: 原始 exit_code；被强制 kill 时为 -1。
        stdout: 标准输出（沙箱限制内可读）。
        stderr: 标准错误。
        wall_seconds: 墙钟耗时（秒）。
        violation: 若发生越界则给出原因（路径/超时/超额）；None 表示无违规。
    """

    model_config = ConfigDict(frozen=True)

    success: bool
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    wall_seconds: float = 0.0
    violation: str | None = None


class SandboxViolation(Exception):
    """沙箱层主动拦截（越界路径 / 超时 / 超额）时抛的异常。

    这个异常只在 sandbox 内部使用——对外暴露为 SandboxResult.violation，
    不会冒泡到 Worker.execute 或 run_loop。
    """
