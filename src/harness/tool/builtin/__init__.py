"""内建工具：bash、read_file、write_file、http_get。

全部继承 :class:`harness.tool.base.BaseTool`，手写 name / description / parameters，
不依赖 @tool 装饰器——因为这些工具需要额外的安全约束（路径沙箱、命令白名单等）。
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import time
from pathlib import Path
from typing import Any

import httpx

from ..base import BaseTool, ToolResult

# ---------------------------------------------------------------------------
# 共享常量 & 工具函数
# ---------------------------------------------------------------------------

_MAX_FILE_SIZE = 1024 * 1024  # 1 MB
_FORBIDDEN_SCHEMES = {"file", "ftp", "gopher", "data", "ldap", "dict", "jar"}
# 禁止 shell 元字符（即便走 subprocess_exec 不走 shell，也能把链式调用拒之门外）
_BASH_ALLOWED = re.compile(r"^[\w\s\-/_.]+$", re.ASCII)


def _resolve_within_cwd(raw: str) -> Path:
    """解析路径并断言在 cwd 内，越界抛 ValueError。"""
    root = Path.cwd().resolve()
    target = Path(raw).resolve() if os.path.isabs(raw) else (root / raw).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"路径越界: {raw!r} 不在 cwd 内") from exc
    return target


# ---------------------------------------------------------------------------
# BashTool
# ---------------------------------------------------------------------------

class BashTool(BaseTool):
    """执行一条 shell 命令，返回 stdout+stderr。

    安全约束：命令必须匹配 ``[\w\s\-/_.]+`` 白名单；实际调用
    ``asyncio.create_subprocess_exec``，不走 shell。
    """

    name = "bash"
    description = "Execute a shell command and return stdout+stderr. No shell metacharacters."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer", "default": 30},
        },
        "required": ["command"],
    }
    readonly = False

    async def execute(self, **args: Any) -> ToolResult:
        cmd = str(args.get("command", "")).strip()
        timeout = int(args.get("timeout", 30))

        if not cmd:
            return ToolResult(ok=False, output="", error="command 不能为空")
        if not _BASH_ALLOWED.match(cmd):
            return ToolResult(
                ok=False,
                output="",
                error="command 仅允许 ASCII 字母数字、空格和 /-_.",
            )

        try:
            argv = shlex.split(cmd, posix=True)
        except ValueError as exc:
            return ToolResult(ok=False, output="", error=f"命令解析失败: {exc}")

        t0 = time.perf_counter()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=Path.cwd(),
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=float(timeout))
        except asyncio.TimeoutError:
            return ToolResult(
                ok=False, output="", error=f"超时 ({timeout}s)",
                execution_time_ms=(time.perf_counter() - t0) * 1000.0,
            )
        except FileNotFoundError:
            return ToolResult(ok=False, output="", error=f"可执行文件不存在: {argv[0]!r}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, output="", error=f"{type(exc).__name__}: {exc}")

        ms = (time.perf_counter() - t0) * 1000.0
        rc = proc.returncode
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        output = stdout if not stderr else (stdout + ("\n" if stdout else "") + "[stderr]\n" + stderr)
        return ToolResult(
            ok=(rc == 0), output=output,
            error=None if rc == 0 else f"exit code {rc}",
            execution_time_ms=ms,
        )


# ---------------------------------------------------------------------------
# ReadFileTool
# ---------------------------------------------------------------------------

class ReadFileTool(BaseTool):
    """读取 cwd 内一个 ≤1MB 的文件，支持行范围。"""

    name = "read_file"
    description = "Read a file's content (within cwd, ≤1MB) with optional line range."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "default": 0},
            "end_line": {"type": ["integer", "null"], "default": None},
        },
        "required": ["path"],
    }
    readonly = True

    async def execute(self, **args: Any) -> ToolResult:
        path_raw = str(args.get("path", ""))
        start_line = int(args.get("start_line", 0))
        end_line = args.get("end_line", None)

        t0 = time.perf_counter()
        try:
            target = _resolve_within_cwd(path_raw)
            if not target.is_file():
                return ToolResult(ok=False, output="", error=f"文件不存在: {target}")
            if target.stat().st_size > _MAX_FILE_SIZE:
                return ToolResult(ok=False, output="", error=f"文件超过 {_MAX_FILE_SIZE}B 上限")

            def _read() -> str:
                return target.read_text(encoding="utf-8", errors="replace")

            content = await asyncio.to_thread(_read)
            lines = content.splitlines(keepends=True)
            end_idx = len(lines) if end_line is None else min(int(end_line), len(lines))
            selected = "".join(lines[start_line:end_idx])
        except ValueError as exc:
            return ToolResult(ok=False, output="", error=str(exc))
        except Exception as exc:  # noqa: BLE001
            ms = (time.perf_counter() - t0) * 1000.0
            return ToolResult(ok=False, output="", error=f"{type(exc).__name__}: {exc}", execution_time_ms=ms)

        ms = (time.perf_counter() - t0) * 1000.0
        return ToolResult(ok=True, output=selected, execution_time_ms=ms)


# ---------------------------------------------------------------------------
# WriteFileTool
# ---------------------------------------------------------------------------

class WriteFileTool(BaseTool):
    """向 cwd 内一个路径写入或追加内容。"""

    name = "write_file"
    description = "Write or append content to a file within cwd."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "append": {"type": "boolean", "default": False},
        },
        "required": ["path", "content"],
    }
    readonly = False

    async def execute(self, **args: Any) -> ToolResult:
        path_raw = str(args.get("path", ""))
        content = str(args.get("content", ""))
        append = bool(args.get("append", False))

        t0 = time.perf_counter()
        try:
            target = _resolve_within_cwd(path_raw)
            target.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"

            def _do_write() -> int:
                with open(target, mode, encoding="utf-8") as fp:
                    fp.write(content)
                return target.stat().st_size

            size = await asyncio.to_thread(_do_write)
        except ValueError as exc:
            return ToolResult(ok=False, output="", error=str(exc))
        except OSError as exc:
            ms = (time.perf_counter() - t0) * 1000.0
            return ToolResult(ok=False, output="", error=f"写文件失败: {exc}", execution_time_ms=ms)

        ms = (time.perf_counter() - t0) * 1000.0
        verb = "appended to" if append else "wrote"
        return ToolResult(ok=True, output=f"OK: {verb} {target} ({size} bytes)", execution_time_ms=ms)


# ---------------------------------------------------------------------------
# HttpGetTool
# ---------------------------------------------------------------------------

class HttpGetTool(BaseTool):
    """向外部 URL 发 GET 请求，返回 status + body。

    安全约束：只允许 http/https，禁止 file://、ftp://、data: 等 scheme。
    """

    name = "http_get"
    description = "Send an HTTP(S) GET request and return status code + response body."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "timeout": {"type": "integer", "default": 15},
        },
        "required": ["url"],
    }
    readonly = True

    async def execute(self, **args: Any) -> ToolResult:
        url = str(args.get("url", "")).strip()
        timeout = float(args.get("timeout", 15))

        # scheme 校验
        if "://" in url:
            scheme = url.split("://", 1)[0].lower()
            if scheme in _FORBIDDEN_SCHEMES:
                return ToolResult(ok=False, output="", error=f"禁止的 scheme: {scheme!r}")
            if scheme not in ("http", "https"):
                return ToolResult(ok=False, output="", error=f"只允许 http/https, 拿到 {scheme!r}")
        else:
            return ToolResult(ok=False, output="", error="URL 必须带 http(s):// scheme")

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
                resp = await client.get(url, follow_redirects=True)
        except httpx.TimeoutException:
            return ToolResult(ok=False, output="", error=f"超时 ({timeout}s)",
                             execution_time_ms=(time.perf_counter() - t0) * 1000.0)
        except httpx.RequestError as exc:
            return ToolResult(ok=False, output="", error=f"httpx {type(exc).__name__}: {exc}",
                             execution_time_ms=(time.perf_counter() - t0) * 1000.0)

        ms = (time.perf_counter() - t0) * 1000.0
        return ToolResult(
            ok=(200 <= resp.status_code < 400),
            output=f"[status {resp.status_code}]\n{resp.text}",
            error=None if 200 <= resp.status_code < 400 else f"HTTP {resp.status_code}",
            execution_time_ms=ms,
        )


__all__ = ["BashTool", "ReadFileTool", "WriteFileTool", "HttpGetTool"]
