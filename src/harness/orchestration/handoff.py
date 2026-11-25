"""Worker 间移交（Handoff）协议。

定位（roadmap 0.2）：handoff 是**补充协议**，不作主模式——Worker 在
TaskResult 里声明 ``handoff_to + handoff_context``，由 Coordinator 负责
路由给目标 Worker（目标 Worker 拿到的是全新隔离会话，只带移交摘要）。

本模块只做两件事：
    1. :class:`HandoffDeclaration` —— 移交声明的数据契约。
    2. :func:`parse_handoff` —— 从 Worker 的纯文本输出里解析移交声明，
       让「不认识 TaskResult 的普通 LLM 输出」也能触发移交。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

# 文本协议标记：Worker 最终输出里出现 `HANDOFF_TO:<worker名>` 即声明移交
HANDOFF_TO_MARKER = "HANDOFF_TO:"
# 可选的第二行：`HANDOFF_CONTEXT:<给下家的上下文摘要>`
HANDOFF_CONTEXT_MARKER = "HANDOFF_CONTEXT:"


class HandoffDeclaration(BaseModel):
    """一次移交声明。

    Attributes:
        from_task: 发起移交的任务 id。
        to_worker: 接收方 Worker 名（必须已注册，否则 Coordinator 拒绝路由）。
        context: 给接收方的上下文摘要；空串表示无附加上下文。
    """

    model_config = ConfigDict(frozen=True)

    from_task: str
    to_worker: str
    context: str = ""


def parse_handoff(output: str, from_task: str) -> HandoffDeclaration | None:
    """从 Worker 输出文本里解析移交声明；没有声明则返回 None。

    解析规则（逐行扫描，宽松匹配——前后允许空白）：
        - 出现 ``HANDOFF_TO:<name>`` → 声明移交，name 去首尾空白。
        - 其后出现的 ``HANDOFF_CONTEXT:<text>`` → 作为移交上下文（取首个）。

    Args:
        output: Worker 的最终 assistant 纯文本输出。
        from_task: 发起移交的任务 id，写入声明的 from_task。

    Returns:
        HandoffDeclaration；未声明移交时返回 None。
    """
    to_worker: str | None = None
    context = ""

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if to_worker is None and line.startswith(HANDOFF_TO_MARKER):
            candidate = line[len(HANDOFF_TO_MARKER):].strip()
            if candidate:
                to_worker = candidate
            continue
        if to_worker is not None and line.startswith(HANDOFF_CONTEXT_MARKER):
            context = line[len(HANDOFF_CONTEXT_MARKER):].strip()
            break

    if to_worker is None:
        return None
    return HandoffDeclaration(from_task=from_task, to_worker=to_worker, context=context)
