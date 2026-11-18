"""模型适配层的抽象基类与能力声明。

Model ABC 定义了 harness 调用任何大模型的统一入口：stream() 返回
AsyncIterator[ChatChunk]，generate() 用默认实现把流式结果收齐成
一个 ChatResponse。子类只需实现 stream()，就能同时获得非流式能力。

供应商差异（SSE 事件格式、cache_control 位置、tool 调用结构）由
OpenAICompat 和 AnthropicModel 各自承担，基类不关心。
"""

from __future__ import annotations

import abc
import json
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..message.msg import Msg
from .cache_profile import CacheMode
from .types import ChatChunk, ChatResponse, GenerateOptions, ToolCall, Usage


class ModelCapabilities(BaseModel):
    """一个模型实例对外宣称的能力边界。

    构造期由 detect_capabilities() 或调用方显式注入；上层会话层据此决定
    要不要打断点、要不要下发 tools、要不要等结构化输出。

    Attributes:
        max_context_tokens: 模型的上下文窗口上限。
        supports_tools: 是否支持 function/tool calling。
        supports_cache_control: 是否支持显式 cache_control 字段。
        supports_structured_output: 是否有官方 JSON 模式 / function schema 强约束。
        supports_streaming: 是否支持 SSE 流式输出。
        cache_mode: 供应商的缓存实现方式，决定是否要打断点。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_context_tokens: int = 32_000
    supports_tools: bool = True
    supports_cache_control: bool = False
    supports_structured_output: bool = False
    supports_streaming: bool = True
    cache_mode: CacheMode = CacheMode.NONE


class Model(abc.ABC):
    """所有大模型适配器的基类。

    子类实现 stream() 就能同时获得 generate()——基类默认把流式输出全部
    收集、拼 text、聚合 ToolCallDelta 成完整 ToolCall，最后返回一个
    ChatResponse。如果供应商有更高效的非流式接口，子类也可以覆盖
    generate() 直接走那条路。
    """

    def __init__(self, *, capabilities: ModelCapabilities | None = None) -> None:
        """初始化一个模型实例。

        Args:
            capabilities: 显式能力声明；None 则在构造时调用
                detect_capabilities() 自动探测。
        """
        self._capabilities = capabilities or self.detect_capabilities()

    @property
    def capabilities(self) -> ModelCapabilities:
        """当前模型的能力声明。"""
        return self._capabilities

    @abc.abstractmethod
    async def stream(
        self,
        messages: list[Msg],
        tools: list[dict[str, Any]],
        options: GenerateOptions,
    ) -> AsyncIterator[ChatChunk]:
        """流式调用模型。

        Args:
            messages: 已装配好的消息列表（含 system / history / 本轮）。
            tools: OpenAI 兼容 schema 格式的工具定义列表；没有工具时为空。
            options: 采样参数、是否流式、缓存画像覆盖等。

        Yields:
            每个 ChatChunk 是一次 SSE 事件解包后的统一形态；最后一块的
            finish_reason 非 None。
        """
        raise NotImplementedError

    async def generate(
        self,
        messages: list[Msg],
        tools: list[dict[str, Any]],
        options: GenerateOptions,
    ) -> ChatResponse:
        """非流式调用，默认靠 stream() 收集实现。

        子类若有原生非流式接口可覆盖本方法以减少一次事件解析。

        Args:
            messages: 已装配好的消息列表。
            tools: 工具定义列表。
            options: 采样参数。

        Returns:
            完整的 ChatResponse。
        """
        # 强制关掉 stream 标志再调 stream()——部分供应商的非流式接口
        # 返回的 JSON 结构和流式 SSE 不同，这里先沿用流解析。
        opts = options
        text_parts: list[str] = []
        # arguments_delta 是分段 JSON 字符串，这里按 index 累积原串，
        # 结束后统一 json.loads 成 dict。
        tool_json_fragments: dict[int, list[str]] = {}
        # id/name 按 index 记
        tool_call_meta: dict[int, ToolCall] = {}
        last_finish_reason = "stop"
        usage = Usage()

        async for chunk in self.stream(messages, tools, opts):
            if chunk.delta:
                text_parts.append(chunk.delta)
            for delta in chunk.tool_calls_delta:
                meta = tool_call_meta.setdefault(
                    delta.index, ToolCall(id="", name="", arguments={})
                )
                if delta.id is not None:
                    meta.id = delta.id
                if delta.name is not None:
                    meta.name = delta.name
                if delta.arguments_delta:
                    tool_json_fragments.setdefault(delta.index, []).append(
                        delta.arguments_delta
                    )
            if chunk.finish_reason is not None:
                last_finish_reason = chunk.finish_reason

        # 所有流结束后，json.loads 拼好的 arguments
        tool_calls: list[ToolCall] = []
        for idx, meta in tool_call_meta.items():
            raw_json = "".join(tool_json_fragments.get(idx, []))
            try:
                arguments = json.loads(raw_json) if raw_json else {}
            except json.JSONDecodeError:
                arguments = {"__raw__": raw_json}
            tool_calls.append(
                ToolCall(id=meta.id, name=meta.name, arguments=arguments)
            )

        return ChatResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=last_finish_reason,
        )

    def detect_capabilities(self) -> ModelCapabilities:
        """探测当前模型实例的能力边界。

        默认返回一组保守的能力；子类应在构造期根据 base_url / model 名称
        推断更准确的值，或者完全跳过自动探测、让调用方显式传入。

        Returns:
            保守的能力声明：32k 上下文、支持 tools、支持流式、无显式缓存。
        """
        return ModelCapabilities(
            max_context_tokens=32_000,
            supports_tools=True,
            supports_cache_control=False,
            supports_structured_output=False,
            supports_streaming=True,
            cache_mode=CacheMode.NONE,
        )
