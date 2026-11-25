"""MCP (Model Context Protocol) stdio 适配器壳（Phase 12 - McpStdioAdapter）。

把一个外部 MCP server 进程用 subprocess 拉起，通过 stdin/stdout 做
JSON-RPC 2.0 通信。这是壳实现——协议层只做 send/receive 的基本封装，
不处理具体 MCP tool 注册。

**关键设计**：config 缺失（或 command 找不到）时构造仍能跑，但所有
方法会抛 ConfigurationError；server 启动时会检测 ``ready_for_use``。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
from typing import Any, AsyncIterator

from ..channel import ChannelAdapter, RawMessage, SendResult
from .feishu import ConfigurationError  # 与 feishu 共用同一异常类型

log = logging.getLogger(__name__)


class McpStdioAdapter(ChannelAdapter):
    """通过 subprocess 启动 MCP server、stdin/stdout 做 JSON-RPC 的适配器。

    channel_name = "mcp_stdio"。
    """

    channel_name: str = "mcp_stdio"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._proc: asyncio.subprocess.Process | None = None
        # 请求队列：(id, payload, future)
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._recv_task: asyncio.Task[None] | None = None
        self._next_id: int = 0

    # ------------------------------------------------------------------
    # ready 检查
    # ------------------------------------------------------------------

    @property
    def ready_for_use(self) -> bool:
        """config 里同时有 command 且该命令在系统里能找到。"""
        cmd = self.config.get("command")
        if not cmd:
            return False
        # command 是绝对路径的话直接检查；否则用 shutil.which
        if os.path.isabs(cmd):
            return os.path.exists(cmd)
        return shutil.which(cmd) is not None

    # ------------------------------------------------------------------
    # 启动 / 关闭 subprocess
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """拉起 MCP server 进程并启动接收循环。

        Raises:
            ConfigurationError: config 缺失或 command 不存在。
        """
        if not self.ready_for_use:
            raise ConfigurationError(
                f"McpStdioAdapter config 缺失或 command 找不到: {self.config}"
            )

        cmd = self.config["command"]
        args = list(self.config.get("args", []))

        log.info("McpStdioAdapter 启动: %s %s", cmd, args)
        self._proc = await asyncio.create_subprocess_exec(
            cmd, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def stop(self) -> None:
        """终止进程和接收循环。"""
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=2.0)
            except Exception:  # noqa: BLE001
                try:
                    self._proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        self._proc = None

    # ------------------------------------------------------------------
    # ChannelAdapter 实现
    # ------------------------------------------------------------------

    async def receive(self) -> AsyncIterator[RawMessage]:
        """receive 是 stub——MCP 的 stdin/stdout 由 self._recv_loop 接管，
        本方法不应被上层直接调用。"""
        import asyncio
        log.debug("McpStdioAdapter.receive() 进入 stub 等待")
        while True:
            await asyncio.sleep(3600)

    async def send(self, message: str, user_id: str, **kwargs: Any) -> SendResult:
        """发一条 JSON-RPC 消息到 MCP server。

        Args:
            message: 消息体（字符串形式；若是 JSON 会自动包成 {"method": message, "params": kwargs}）。
            user_id: 忽略（MCP 无用户概念）。
            **kwargs: 作为 JSON-RPC params。

        Returns:
            SendResult（ok=True 表示写入成功；**不等待远端回复**——
            需要回复请用 :meth:`request`）。
        """
        if not self._proc or self._proc.stdin is None:
            return SendResult(ok=False, error="MCP 进程未启动")
        try:
            if kwargs:
                payload = {
                    "jsonrpc": "2.0",
                    "method": message,
                    "params": kwargs,
                    "id": self._next_id,
                }
            else:
                payload = {
                    "jsonrpc": "2.0",
                    "method": message,
                    "id": self._next_id,
                }
            self._next_id += 1
            line = json.dumps(payload, ensure_ascii=False) + "\n"
            self._proc.stdin.write(line.encode("utf-8"))
            await self._proc.stdin.drain()
            return SendResult(ok=True, message_id=str(payload["id"]))
        except Exception as exc:  # noqa: BLE001
            log.exception("McpStdioAdapter.send 失败")
            return SendResult(ok=False, error=str(exc))

    # ------------------------------------------------------------------
    # JSON-RPC request（需要回复的场景）
    # ------------------------------------------------------------------

    async def request(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = 30.0
    ) -> dict[str, Any]:
        """发一条 JSON-RPC request 并等待 response。

        Args:
            method: JSON-RPC method 名。
            params: 参数（可为 None）。
            timeout: 等待秒数。

        Returns:
            {"result": ...} 或 {"error": ...}。

        Raises:
            asyncio.TimeoutError: 超时。
            RuntimeError: 进程未启动。
        """
        if not self._proc or self._proc.stdin is None:
            raise RuntimeError("MCP 进程未启动")

        msg_id = self._next_id
        self._next_id += 1
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = fut

        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "id": msg_id,
        }
        if params is not None:
            payload["params"] = params

        line = json.dumps(payload, ensure_ascii=False) + "\n"
        self._proc.stdin.write(line.encode("utf-8"))
        await self._proc.stdin.drain()

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise

    # ------------------------------------------------------------------
    # 内部：stdout 接收循环
    # ------------------------------------------------------------------

    async def _recv_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        reader = self._proc.stdout
        buffer = b""
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                log.warning("McpStdioAdapter: stdout 已关闭")
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    log.warning("McpStdioAdapter: 无法解析 JSON: %r", line)
                    continue
                self._dispatch_response(msg)

    def _dispatch_response(self, msg: dict[str, Any]) -> None:
        """把 JSON-RPC response 路由到对应 pending future。"""
        if "id" in msg:
            fut = self._pending.pop(msg["id"], None)
            if fut is not None:
                fut.set_result(msg)
                return
        # notification（没有 id）——暂时忽略
        log.debug("McpStdioAdapter: 收到 notification: %s", msg.get("method"))
