"""模型层的通用数据结构。

这里定义的结构体是两个 Model 子类（OpenAICompat / AnthropicModel）
以及上层会话层都会用到的「通用返回类型」，不包含任何供应商专属
的传输细节。供应商专属的 cache_control、header 拼装逻辑集中在各自
的适配文件里。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, FieldSerializationInfo


@dataclass
class ToolCallDelta:
    """一次工具调用的流式增量片段。

    流式场景下，工具调用按 index 切片逐块返回；同一个 index 可能先
    返回 id/name，随后才是 arguments 的若干段 JSON 片段。调用方需要按
    index 累积这些片段才能拼出完整的 ToolCall。

    Attributes:
        index: 本次调用在同批 tool_calls 里的位置下标。
        id: 工具调用的唯一 ID，通常只在首块出现；None 表示继续上一块。
        name: 工具名，只在首块出现；None 表示继续上一块。
        arguments_delta: 本次追加的参数字符串片段（可能为空串）。
    """

    index: int = 0
    id: str | None = None
    name: str | None = None
    arguments_delta: str = ""


@dataclass
class ToolCall:
    """一次完整的工具调用。

    非流式 generate() 的返回值里每一个 ToolCall 都已经是拼好的；
    流式路径则是上层用 ToolCallDelta 累积出来的结果。

    Attributes:
        id: 工具调用 ID，供 tool result 关联。
        name: 被调工具名。
        arguments: 解析好的参数字典。
    """

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class Usage:
    """供应商返回的 token 用量。

    cache_read_tokens 只在供应商报告缓存命中时才有值，为 0 表示「未知」——
    可能是供应商不支持、也可能是这轮刚好没命中。两种情况上层都不应该
    贸然断言。

    Attributes:
        prompt_tokens: 本次请求消耗的输入 token（含缓存未命中部分）。
        completion_tokens: 本次生成的输出 token。
        total_tokens: 总和；部分供应商会自己算好，没有就填 prompt + completion。
        cache_read_tokens: 缓存命中节省的 token；供应商未报告时为 0。
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass
class ChatChunk:
    """流式输出的一块增量。

    供应商 SSE 事件解包后的统一形态。delta 是文本增量；tool_calls_delta
    是工具调用增量列表；finish_reason 在最末块才非 None。

    Attributes:
        delta: 本次追加的文本片段。
        tool_calls_delta: 本次追加的工具调用片段列表。
        finish_reason: 生成结束原因（如 "stop"、"tool_calls"、"length"）；
            中间块为 None。
        raw: 原始 SSE payload，用于上层做 debug 或供应商专属解析。
    """

    delta: str = ""
    tool_calls_delta: list[ToolCallDelta] = field(default_factory=list)
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatResponse:
    """非流式 / 收集完流式后的完整响应。

    generate() 的直接返回值；stream() 的上层消费者也会把所有 ChatChunk
    累积成一个 ChatResponse 再继续。

    Attributes:
        text: 完整文本输出。
        tool_calls: 已拼好的工具调用列表。
        usage: token 用量。
        finish_reason: 结束原因。
    """

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    finish_reason: str = "stop"


class GenerateOptions(BaseModel):
    """一次生成调用的可调参数。

    frozen 配置使得同一份 options 可以安全复用到并发场景。cache_profile_override
    预留了「这一轮强制改缓存画像」的入口，默认 None 表示照 Model 构造时的画像来。

    Attributes:
        temperature: 采样温度。0 表示近似贪心解码。
        top_p: nucleus 采样阈值；None 表示不用 top-p。
        max_tokens: 本次最多生成多少 token；None 用供应商缺省。
        stop: 停止序列列表。
        stream: 是否以流式方式返回。
        cache_profile_override: 本轮强制覆盖缓存画像。
        extra: 透传给供应商的其他未知字段，方便应对新参数。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    temperature: float = 0.7
    top_p: float | None = None
    max_tokens: int | None = None
    stop: list[str] = Field(default_factory=list)
    stream: bool = True
    cache_profile_override: Any | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
