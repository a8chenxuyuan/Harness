"""MCP (Model Context Protocol) 客户端：JSON-RPC 2.0 over stdio。

当前只实现 stdio 传输（subprocess），后续可扩展 sse / http。
接口设计贴近 MCP 官方协议：先 initialize，然后 tools.list / tools.call。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

log = logging.getLogger(__name__)


class McpError(Exception):
    """MCP 协议错误（从 JSON-RPC error 字段映射而来）。"""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"MCP error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


class McpClient:
    """MCP 客户端（stdio 传输）。

    **使用流程**：
        1. 构造 McpClient(command, args, env)
        2. await client.connect()        # 启动子进程
        3. tools = await client.tools_list()     # 拿工具列表
        4. result = await client.tools_call(name, {"arg": val})
        5. await client.close()

    Attributes:
        command: 要启动的可执行程序。
        args: 命令行参数列表。
        env: 额外环境变量（会与当前进程环境合并）。
        _proc: 子进程对象，connect 后才可用。
        _request_id: JSON-RPC id 计数器，单调递增。
    """

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.command = command
        self.args = list(args or [])
        self.env = env
        self._proc: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._lock = asyncio.Lock()  # 保护 request_id 递增与 stdio 发送顺序

    # --- 生命周期 --------------------------------------------------------------

    async def connect(self) -> dict[str, Any]:
        """启动子进程并完成 initialize 握手。

        Returns:
            MCP server 的 initialize 响应（包含 serverInfo、protocolVersion 等）。

        Raises:
            McpError: initialize 返回错误。
            RuntimeError: 子进程启动失败。
        """
        # 合并环境变量
        merged_env = os.environ.copy()
        if self.env:
            merged_env.update(self.env)

        try:
            self._proc = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"MCP: 找不到可执行文件 {self.command!r}") from exc

        # 后台监听 stderr，只打日志，不阻塞主流程
        assert self._proc.stderr is not None
        asyncio.create_task(self._drain_stderr())

        # 发送 initialize
        response = await self._send(
            method="initialize",
            params={
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "harness", "version": "0.1.0"},
            },
        )
        log.info("MCP: initialize 成功 — server=%s", response.get("serverInfo"))
        return response

    async def close(self) -> None:
        """优雅关闭：先发 exit，再 kill 进程。幂等。"""
        if self._proc is None:
            return
        try:
            await asyncio.wait_for(self._send("notifications/exit", None), timeout=2.0)
        except Exception:  # noqa: BLE001 - 关闭阶段不关心错误
            pass

        try:
            if self._proc.returncode is None:
                self._proc.terminate()
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    self._proc.kill()
        except Exception as exc:  # noqa: BLE001
            log.debug("MCP close: 清理进程时出错 — %s", exc)
        self._proc = None

    async def __aenter__(self) -> "McpClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # --- MCP 高层 API ----------------------------------------------------------

    async def tools_list(self) -> list[dict[str, Any]]:
        """列出 server 提供的所有工具。

        Returns:
            [{"name", "description", "inputSchema", ...}] 字典列表。
        """
        response = await self._send("tools/list")
        return response.get("tools", [])

    async def tools_call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """调用一个 MCP 工具。

        Args:
            name: 工具名。
            arguments: 参数字典。

        Returns:
            {"content": [...], "isError": bool} 结构。
        """
        response = await self._send(
            "tools/call",
            params={"name": name, "arguments": arguments or {}},
        )
        return response

    async def prompts_list(self) -> list[dict[str, Any]]:
        """可选：列出 MCP prompts。没实现也不会报错，server 可能回 error。"""
        try:
            response = await self._send("prompts/list")
            return response.get("prompts", [])
        except McpError as exc:
            log.debug("MCP: prompts/list 不支持 — %s", exc)
            return []

    # --- JSON-RPC 底层 ---------------------------------------------------------

    async def _send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """发送一个 JSON-RPC 请求（带 id）或通知（不带 id）并读回响应。

        Args:
            method: JSON-RPC method 名。
            params: 参数字典。通知可为 None。

        Returns:
            result 字段内容（成功时）。

        Raises:
            McpError: JSON-RPC error。
            RuntimeError: 连接未建立或读超时。
        """
        if self._proc is None:
            raise RuntimeError("MCP: 未连接，请先 connect()")
        assert self._proc.stdin is not None
        assert self._proc.stdout is not None

        async with self._lock:
            self._request_id += 1
            is_notification = method.startswith("notifications/")
            request: dict[str, Any] = {
                "jsonrpc": "2.0",
                "method": method,
            }
            if not is_notification:
                request["id"] = self._request_id
            if params is not None:
                request["params"] = params

            line = json.dumps(request, ensure_ascii=False) + "\n"
            self._proc.stdin.write(line.encode("utf-8"))
            await self._proc.stdin.drain()

            if is_notification:
                # 通知不需要响应
                return {}

            # 读一行 JSON-RPC 响应
            raw = await self._proc.stdout.readline()
            if not raw:
                # 进程可能已经退出
                rc = self._proc.returncode
                if rc is not None and rc != 0:
                    log.warning("MCP: 子进程意外退出 code=%d", rc)
                raise RuntimeError("MCP: 子进程 stdout 关闭，未收到响应")

            try:
                response = json.loads(raw.decode("utf-8").strip())
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"MCP: 响应不是合法 JSON — {raw!r}") from exc

        if "error" in response:
            err = response["error"]
            raise McpError(
                code=int(err.get("code", -1)),
                message=str(err.get("message", "unknown")),
                data=err.get("data"),
            )

        return response.get("result", {})

    # --- stderr 监听 -----------------------------------------------------------

    async def _drain_stderr(self) -> None:
        """后台任务：持续读取并打印 stderr，避免子进程因 pipe 满而阻塞。"""
        assert self._proc is not None and self._proc.stderr is not None
        try:
            while True:
                line = await self._proc.stderr.readline()
                if not line:
                    break
                # stderr 通常是服务端日志，打 debug 方便排查
                log.debug("MCP[stderr] %s", line.decode("utf-8", errors="replace").rstrip())
        except Exception as exc:  # noqa: BLE001
            log.debug("MCP: stderr 监听结束 — %s", exc)
