"""McpTool：把一个 MCP server 工具适配成 core 层 BaseTool。

适配器是**无状态**的：每次 execute() 都新建一个 McpClient 与目标
server 建立连接、调用工具、然后关闭。这样不需要长期持有子进程句柄，
server 崩溃也不会让注册表里的工具失效，代价是每次调用多一次握手
（本地 stdio 场景通常 <100ms，可接受）。

工具名直接沿用 MCP server 声明的 name。若多个 server 暴露同名工具，
ToolRegistry 按"后注册覆盖前注册"处理（与内置工具行为一致）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from harness.core.tool.base import BaseTool, ToolResult

from .client import McpClient

log = logging.getLogger(__name__)


class McpTool(BaseTool):
    """一个 MCP server 工具的本地适配器。

    Attributes:
        name: 注册进 ToolRegistry 的名字（沿用 MCP 工具名）。
        description: 工具说明，来自 MCP tools/list。
        parameters: 入参 JSON Schema，来自 MCP 的 inputSchema。
        readonly: MCP 协议没有只读语义，适配器默认 True：保证调试面板可以
            试跑外部工具；代价是 Agent 并行调度会把它当只读工具同批并发。
            若接入确知有副作用的 server，注册后可手动改此标记。
        server_name: 来源 MCP server 的名字，供工具市场展示来源。
        command/args/env: 重连 server 所需的启动配置。
        timeout: 单次调用（握手+执行）的超时秒数。
    """

    def __init__(
        self,
        *,
        server_name: str,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 30.0,
        readonly: bool = True,
    ) -> None:
        self.server_name = server_name
        self.name = name
        self.description = description
        self.parameters = input_schema or {"type": "object", "properties": {}}
        self.readonly = readonly
        self.command = command
        self.args = list(args or [])
        self.env = env
        self.timeout = timeout

    async def execute(self, **args: Any) -> ToolResult:
        """新建连接调用远端 MCP 工具，返回 ToolResult。

        任何异常（连接失败、协议错误、超时）都转成 ok=False 的
        ToolResult，不向上抛——与内置工具的容错风格一致。
        """
        import time

        started = time.monotonic()
        client = McpClient(self.command, self.args, self.env)
        try:
            await asyncio.wait_for(client.connect(), timeout=self.timeout)
            response = await asyncio.wait_for(
                client.tools_call(self.name, args), timeout=self.timeout
            )
            elapsed_ms = (time.monotonic() - started) * 1000

            # MCP 结果结构：{"content": [{type, text, ...}], "isError": bool}
            is_error = bool(response.get("isError", False))
            parts: list[str] = []
            for block in response.get("content", []):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                else:
                    parts.append(json.dumps(block, ensure_ascii=False))
            output = "\n".join(parts)

            return ToolResult(
                ok=not is_error,
                output=output,
                error=output if is_error else None,
                execution_time_ms=round(elapsed_ms, 2),
            )
        except asyncio.TimeoutError:
            elapsed_ms = (time.monotonic() - started) * 1000
            return ToolResult(
                ok=False,
                output="",
                error=f"MCP 调用超时（>{self.timeout}s）",
                execution_time_ms=round(elapsed_ms, 2),
            )
        except Exception as exc:  # noqa: BLE001 - 统一转 ToolResult，不打断调用方
            log.warning("McpTool %s 执行失败: %s", self.name, exc)
            elapsed_ms = (time.monotonic() - started) * 1000
            return ToolResult(
                ok=False,
                output="",
                error=str(exc),
                execution_time_ms=round(elapsed_ms, 2),
            )
        finally:
            await client.close()
