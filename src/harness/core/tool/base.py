"""工具基类与执行结果数据模型。

本模块定义 ToolResult（一次工具调用的返回值）和 BaseTool（所有工具的抽象基类）。
具体工具子类或由 @tool 装饰器反射生成，或直接继承 BaseTool 手写。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolResult(BaseModel):
    """一次工具调用的结果。

    Attributes:
        ok: 是否执行成功。False 时 error 应提供诊断。
        output: 工具输出（stdout、文件内容、HTTP 响应体等）。
        error: 失败原因，可选。
        execution_time_ms: 执行耗时，毫秒。
        truncated: output 是否因预算被截断。
    """

    model_config = ConfigDict(frozen=True)

    ok: bool
    output: str
    error: str | None = None
    execution_time_ms: float = 0.0
    truncated: bool = False


class BaseTool(ABC):
    """所有工具的抽象基类。

    子类必须实现 execute，并提供 name / description / parameters。
    若使用 @tool 装饰器，这三者会被反射自动填充。
    """

    # 这三个字段允许子类（或 @tool 注入）在 __init__ 之外直接赋值
    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    readonly: bool = True

    @abstractmethod
    async def execute(self, **args: Any) -> ToolResult:
        """执行工具。

        Args:
            **args: 由 JSON Schema 校验后的参数，与 parameters 中定义的字段对应。

        Returns:
            ToolResult 实例。
        """

    def to_openai_schema(self) -> dict[str, Any]:
        """导出为 OpenAI / 兼容供应商可直接使用的 function calling schema。

        Returns:
            形如 ``{"type": "function", "function": {...}}`` 的字典。
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def __repr__(self) -> str:  # pragma: no cover - 调试友好
        return f"<{type(self).__name__} name={self.name!r} readonly={self.readonly}>"
