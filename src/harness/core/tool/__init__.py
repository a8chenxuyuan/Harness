"""工具系统（Phase 4）。

对外导出：
    * BaseTool / ToolResult —— 基类与结果模型
    * tool —— @tool 反射装饰器
    * ToolRegistry —— 工具注册表
    * ToolBudget —— 结果截断 + 调用去重
    * 四个内建工具：BashTool / ReadFileTool / WriteFileTool / HttpGetTool
"""

from .admission import ConflictGroup, plan_batch
from .base import BaseTool, ToolResult
from .budget import ToolBudget
from .builtin import BashTool, HttpGetTool, ReadFileTool, WriteFileTool
from .executor import ToolExecutor, execute_with_overlap
from .reflective import tool
from .registry import ToolRegistry

__all__ = [
    "BaseTool",
    "BashTool",
    "ConflictGroup",
    "HttpGetTool",
    "ReadFileTool",
    "ToolBudget",
    "ToolExecutor",
    "ToolRegistry",
    "ToolResult",
    "WriteFileTool",
    "execute_with_overlap",
    "plan_batch",
    "tool",
]
