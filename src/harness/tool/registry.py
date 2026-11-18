"""工具注册表。

一个 :class:`ToolRegistry` 就是 ``name → BaseTool`` 的有序映射，
同时提供 LLM 直接可用的 schema 导出和读写分组。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from .base import BaseTool

log = logging.getLogger(__name__)


class ToolRegistry:
    """集中管理所有工具的注册表。

    典型用法::

        registry = ToolRegistry()
        registry.register(read_file_tool)
        @registry.add
        @tool
        async def write_file(...): ...

    Attributes:
        _tools: 内部存储，key 为 tool.name。
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    # --- 注册 -----------------------------------------------------------------

    def register(self, tool: BaseTool) -> None:
        """注册一个工具。同名工具后注册覆盖前注册，并打印 warning。

        Args:
            tool: 继承自 :class:`BaseTool` 的实例。
        """
        if not isinstance(tool, BaseTool):
            raise TypeError(f"ToolRegistry.register 需要 BaseTool 实例，拿到 {type(tool)!r}")
        if not tool.name:
            raise ValueError("工具 name 不能为空")
        if tool.name in self._tools:
            log.warning(
                "ToolRegistry: 同名工具 %r 已存在，将被新工具覆盖 (old=%s → new=%s)",
                tool.name,
                type(self._tools[tool.name]).__name__,
                type(tool).__name__,
            )
        self._tools[tool.name] = tool

    def add(
        self,
        target: BaseTool | Any = None,
        *,
        readonly: bool | None = None,
    ) -> BaseTool | Any:
        """既可当 ``@registry.add`` 装饰器（接 BaseTool 或 ReflectiveTool），
        也可当 ``registry.add(tool_instance)`` 直接调用。

        若装饰的是一个裸函数，会自动套上 @tool（readonly 取 keyword 或默认 True）。
        """
        from .reflective import ReflectiveTool, tool as _tool_decorator  # 延迟导入避免循环

        def _coerce(obj: Any) -> BaseTool:
            if isinstance(obj, BaseTool):
                return obj
            # 裸函数 → 套 @tool
            return _tool_decorator(obj, readonly=readonly if readonly is not None else True)

        if target is None:
            # keyword-only: @registry.add() 或 @registry.add(readonly=False)
            def _decorator(obj: Any) -> Any:
                instance = _coerce(obj)
                self.register(instance)
                return instance
            return _decorator

        instance = _coerce(target)
        self.register(instance)
        return instance

    # --- 查询 -----------------------------------------------------------------

    def get(self, name: str) -> BaseTool:
        """按名称取工具，不存在抛 KeyError。"""
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"ToolRegistry 中不存在名为 {name!r} 的工具") from exc

    def list_for_llm(self) -> list[dict[str, Any]]:
        """导出所有工具的 OpenAI function calling schema。

        Returns:
            按名称排序的 schema 列表。
        """
        return [self._tools[k].to_openai_schema() for k in sorted(self._tools)]

    @property
    def readonly_tools(self) -> list[BaseTool]:
        """只读工具（readonly=True）。"""
        return [t for t in self._tools.values() if t.readonly]

    @property
    def write_tools(self) -> list[BaseTool]:
        """写工具（readonly=False）。"""
        return [t for t in self._tools.values() if not t.readonly]

    # --- 容器协议 -------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._tools)

    def __iter__(self) -> Iterator[BaseTool]:
        return iter(self._tools.values())

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools

    def __repr__(self) -> str:  # pragma: no cover - 调试友好
        return f"<ToolRegistry n={len(self._tools)} names={sorted(self._tools)}>"
