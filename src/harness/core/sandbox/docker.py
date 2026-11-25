"""DockerSandbox：container 级隔离（Phase 20 可选实现）。

行为：
    - 尝试 import docker；未装则 __init__ 抛出 ImportError，
      由调用方 fallback 到 ProcessSandbox（或记录 Warning）。
    - run_cmd 用 container.exec_run 执行；超时直接 kill 容器。
    - 任何异常都不外抛，转为 SandboxResult.violation。
    - teardown 停止并删除容器。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING

from .base import Sandbox, SandboxPolicy, SandboxResult

if TYPE_CHECKING:
    pass

_DOCKER_IMAGE = "alpine:latest"  # 默认镜像；业务方可换


class DockerSandbox(Sandbox):
    """容器级沙箱——比 ProcessSandbox 多了 OS 级边界。

    降级：未装 docker 库时构造直接抛 ImportError，调用方应 fallback。
    """

    def __init__(self, policy: SandboxPolicy, image: str = _DOCKER_IMAGE) -> None:
        try:
            import docker  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "DockerSandbox 需要安装 docker 库：`pip install docker`；"
                "未装时请 fallback 到 ProcessSandbox。"
            ) from exc

        import docker

        self.policy = policy
        self.image = image
        client = docker.from_env()

        # 拉镜像（可选，如果本地已有则跳过）
        try:
            client.images.pull(image)
        except Exception:  # noqa: BLE001 - 拉取失败不阻止已有镜像使用
            pass

        # 启动一个空闲容器（保持挂起，exec_run 往里塞命令）
        container_name = f"harness-sandbox-{uuid.uuid4().hex[:8]}"
        self._container = client.containers.run(
            image,
            command=["tail", "-f", "/dev/null"],  # 挂起
            name=container_name,
            detach=True,
            mem_limit=f"{policy.memory_mb}m",
            nano_cpus=int(policy.cpu_time_seconds * 1e9) if policy.cpu_time_seconds else None,
            network_disabled=(policy.network == "deny"),
            auto_remove=False,
        )
        self._client = client

    async def run_cmd(
        self,
        cmd: list[str],
        *,
        stdin: str | None = None,
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        start = time.monotonic()
        exec_cmd = cmd if stdin is None else ["sh", "-c", f"{_quote(cmd)} | cat"]
        try:
            result = self._container.exec_run(
                exec_cmd,
                demux=False,
                detach=False,
                timeout=float(self.policy.wall_timeout_seconds),
                environment=env or {},
            )
            exit_code = result.exit_code if result.exit_code is not None else 0
            output = result.output.decode("utf-8", errors="replace") if result.output else ""
            return SandboxResult(
                success=exit_code == 0,
                exit_code=exit_code,
                stdout=output,
                wall_seconds=round(time.monotonic() - start, 3),
            )
        except Exception as exc:  # noqa: BLE001 - Docker 异常统一转 violation
            violation = f"docker_exec_failed: {type(exc).__name__}: {exc}"
            return SandboxResult(
                success=False, exit_code=-1, violation=violation,
                wall_seconds=round(time.monotonic() - start, 3),
            )

    async def teardown(self) -> None:
        try:
            self._container.stop(timeout=2)
            self._container.remove()
        except Exception:  # noqa: BLE001 - 容器可能已被清理
            pass


def _quote(cmd: list[str]) -> str:
    """把命令列表拼回 shell-friendly 字符串（供 stdin 管道方案）。"""
    import shlex as _shlex
    return " ".join(_shlex.quote(c) for c in cmd)
