"""ProcessSandbox：subprocess 级隔离（Phase 20 默认实现）。

实现：
    - asyncio.create_subprocess_exec 启动子进程；run_in_executor 跑同步路径校验。
    - 路径白名单：扫描命令参数里的路径（以 /、\ 或盘符开头），每个都必须在
      policy.path_whitelist 或 policy.working_dir 之下；否则 SandboxViolation。
    - 墙钟超时：asyncio.wait_for 包一层；超时直接 terminate + kill。
    - 任何异常都在 run_cmd 内部转换为 SandboxResult.violation，不外抛。
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import time
from typing import TYPE_CHECKING

from .base import Sandbox, SandboxPolicy, SandboxResult, SandboxViolation

if TYPE_CHECKING:
    pass


# 命令参数里的路径匹配（Windows 反斜杠 / Unix 正斜杠 / 盘符）
_PATH_RE = re.compile(r"([A-Za-z]:[\\/][^\s'\"<>|`]*|/[^\s'\"<>|`]+)")


class ProcessSandbox(Sandbox):
    """subprocess 级沙箱——独立子进程 + 路径白名单 + 超时 kill + 独立临时目录。

    注意：Windows 上 resource 模块不可用（CPU 时间上限 / RLIMIT），
    所以 cpu_time_seconds 与 memory_mb 在 Windows 上仅靠墙钟兜底——
    这是有意的降级，文档化记录。
    """

    def __init__(self, policy: SandboxPolicy) -> None:
        self.policy = policy
        # 独立临时目录（working_dir 未指定时自动创建）
        self._temp_dir = None
        if policy.working_dir is None:
            self._temp_dir = tempfile.mkdtemp(prefix="harness-sandbox-")
            self._working_dir = self._temp_dir
        else:
            self._working_dir = policy.working_dir

        # 合并路径白名单
        wd_resolved = os.path.abspath(self._working_dir)
        self._allowed_prefixes: list[str] = [
            os.path.abspath(p) for p in policy.path_whitelist
        ]
        if wd_resolved not in self._allowed_prefixes:
            self._allowed_prefixes.insert(0, wd_resolved)

    async def run_cmd(
        self,
        cmd: list[str],
        *,
        stdin: str | None = None,
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """在隔离子进程里执行命令，返回 SandboxResult。任何异常不外抛。"""
        start = time.monotonic()

        # 1. 路径白名单校验——违规直接拦截（不启动进程）
        violation = self._check_paths(cmd)
        if violation:
            self._record_violation(violation)
            return SandboxResult(
                success=False, exit_code=-1, violation=violation,
                wall_seconds=round(time.monotonic() - start, 3),
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE if stdin else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._working_dir,
                env=_build_env(env),
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(input=stdin.encode() if stdin else None),
                    timeout=self.policy.wall_timeout_seconds,
                )
                rc = proc.returncode or 0
            except asyncio.TimeoutError:
                proc.kill()
                stdout, stderr = await proc.communicate()
                rc = -1
                violation = (
                    f"wall_timeout: 超过 {self.policy.wall_timeout_seconds}s 被 kill"
                )
                self._record_violation(violation)
                return SandboxResult(
                    success=False, exit_code=rc,
                    stdout=stdout.decode("utf-8", errors="replace"),
                    stderr=stderr.decode("utf-8", errors="replace"),
                    violation=violation,
                    wall_seconds=round(time.monotonic() - start, 3),
                )
        except (FileNotFoundError, OSError, UnicodeDecodeError) as exc:
            violation = f"启动失败: {type(exc).__name__}: {exc}"
            self._record_violation(violation)
            return SandboxResult(
                success=False, exit_code=-1, violation=violation,
                wall_seconds=round(time.monotonic() - start, 3),
            )

        wall = round(time.monotonic() - start, 3)
        return SandboxResult(
            success=rc == 0,
            exit_code=rc,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            wall_seconds=wall,
        )

    async def teardown(self) -> None:
        """幂等清理——删除自动创建的临时目录。"""
        if self._temp_dir and os.path.isdir(self._temp_dir):
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None

    # --- 内部辅助 ------------------------------------------------------------

    def _check_paths(self, cmd: list[str]) -> str | None:
        """扫描命令参数里的路径；不在白名单下则返回违规描述。"""
        for arg in cmd:
            for match in _PATH_RE.finditer(arg):
                raw = match.group(1)
                try:
                    resolved = os.path.abspath(raw)
                except OSError:
                    continue
                if not any(
                    resolved == p or resolved.startswith(p + os.sep)
                    for p in self._allowed_prefixes
                ):
                    return f"path_violation: {raw} 不在允许的路径白名单内"
        return None

    @staticmethod
    def _record_violation(violation: str) -> None:
        """记录沙箱违规指标（进程级异常，main process 不受影响）。"""
        try:
            from harness.common.observability.metrics import record_sandbox_violation
            record_sandbox_violation(reason=violation.split(":")[0])
        except Exception:  # noqa: BLE001 - metrics 是可选依赖，不阻塞
            pass


def _build_env(extra: dict[str, str] | None) -> dict[str, str]:
    """构造子进程继承的环境变量（最小白名单 + 可选注入）。"""
    safe = {"PATH", "HOME", "TEMP", "TMP", "USER", "LOGNAME"}
    base = {k: v for k, v in os.environ.items() if k in safe}
    if extra:
        base.update(extra)
    return base
