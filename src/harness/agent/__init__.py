"""Harness Agent 层（core）。

对外暴露两个符号：

- :class:`Agent` —— 所有 Agent 形态的基类（ABC）
- :class:`ReActAgent` —— 主实现：ReAct 循环 + 事件分发 + checkpoint

>>> from harness.agent import ReActAgent
>>> agent = ReActAgent(model=my_model)
>>> state = await agent.run("你好")
"""

from .base import Agent
from .react_agent import ReActAgent

__all__ = [
    "Agent",
    "ReActAgent",
]
