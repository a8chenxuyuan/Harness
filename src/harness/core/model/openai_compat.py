"""OpenAI 兼容的大模型适配器。

覆盖的供应商：OpenAI 官方、DeepSeek、DashScope、Volcengine、本地 Ollama、
vLLM——只要 URL 是 `https://api.xxx.com/v1/chat/completions` 格式的都走这里。

SSE 解析遵循官方 `/v1/chat/completions` 响应格式：
    data: {"choices": [{"delta": {"content": "..."}}]}
    data: {"choices": [{"delta": {"tool_calls": [...]}}]}
    data: [DONE]
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from harness.common.message.msg import Msg
from .base import Model, ModelCapabilities
from .cache_profile import CacheMode, CacheHints
from .types import ChatChunk, GenerateOptions, ToolCall, ToolCallDelta, Usage


def _parse_usage(raw: dict[str, Any]) -> Usage:
    """把供应商的 usage 字典转成统一 Usage。

    DeepSeek 用 `prompt_cache_hit_tokens` 表示缓存命中，OpenAI 用
    `prompt_tokens_details.cached_tokens`，两者都兼容。

    Args:
        raw: SSE 末尾 usage 块或非流式响应里的 usage 字段。

    Returns:
        统一结构的 Usage。
    """
    details = raw.get("prompt_tokens_details") or {}
    prompt = raw.get("prompt_tokens", 0) or 0
    completion = raw.get("completion_tokens", 0) or 0
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=raw.get("total_tokens", 0) or (prompt + completion),
        cache_read_tokens=(
            raw.get("prompt_cache_hit_tokens")
            or details.get("cached_tokens")
            or 0
        ),
    )


# 已知模型的上下文窗口（token）。未命中时退回保守的 32k。
_MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "deepseek-flash": 1_048_576,      # DeepSeek-V4.1-Flash
    "deepseek-v4-pro": 1_048_576,     # DeepSeek-V4-Pro
    "deepseek-v4": 1_048_576,
    "deepseek-chat": 128_000,
    "deepseek-reasoner": 128_000,
}


def _infer_context_window(model: str) -> int:
    """按模型名推断上下文窗口；未知模型退回 32k 保守值。"""
    name = model.lower().strip()
    if name in _MODEL_CONTEXT_WINDOWS:
        return _MODEL_CONTEXT_WINDOWS[name]
    # 兼容 deepseek-v4-xxx 这类衍生名
    if name.startswith("deepseek") and "v4" in name:
        return 1_048_576
    return 32_000


def _msg_to_openai(msg: Msg) -> dict[str, Any]:
    """把 Msg 转成 OpenAI chat/completions 需要的 dict。

    Attributes:
        msg: harness.common.message.msg.Msg。

    Returns:
        {"role": "user"|"assistant"|"system", "content": "..."} 格式的 dict。
    """
    role = msg.role.value
    # OpenAI 侧内容是纯文本，多模态块暂不处理
    content = msg.text()
    out: dict[str, Any] = {"role": role, "content": content}
    if msg.name is not None and role in ("tool", "assistant"):
        out["name"] = msg.name
    return out


class OpenAICompat(Model):
    """OpenAI 兼容接口的模型适配器。

    Attributes:
        base_url: 兼容 OpenAI 的 API 根地址（带 `/v1` 前缀）。
        api_key: API Key；本地 Ollama / vLLM 可能为 None。
        model: 具体模型名，如 `deepseek-chat`。
        timeout: 单次请求超时秒数。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        model: str,
        timeout: float = 30.0,
        capabilities: ModelCapabilities | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model
        self.timeout = timeout
        super().__init__(capabilities=capabilities)

    # ------------------------------------------------------------------
    # 能力探测
    # ------------------------------------------------------------------

    def detect_capabilities(self) -> ModelCapabilities:
        """根据 base_url 推断缓存方式，按模型名推断上下文窗口。

        - URL 含 ollama / localhost → 无缓存
        - 上下文窗口：DeepSeek V4 为 1M，chat/reasoner 为 128k，其余保守 32k

        所有兼容接口默认支持 tools 和 streaming。
        """
        lowered = self.base_url.lower()
        if "deepseek" in lowered:
            cache_mode = CacheMode.AUTOMATIC
        elif "ollama" in lowered or "localhost" in lowered:
            cache_mode = CacheMode.NONE
        else:
            cache_mode = CacheMode.AUTOMATIC
        return ModelCapabilities(
            max_context_tokens=_infer_context_window(self.model_name),
            supports_tools=True,
            supports_cache_control=False,  # OpenAI 兼容接口不支持显式断点
            supports_structured_output=True,
            supports_streaming=True,
            cache_mode=cache_mode,
        )

    # ------------------------------------------------------------------
    # 构建请求体
    # ------------------------------------------------------------------

    def _build_payload(
        self,
        messages: list[Msg],
        tools: list[dict[str, Any]],
        options: GenerateOptions,
    ) -> dict[str, Any]:
        """拼请求体，cache_control 只在 EXPLICIT 时下发。"""
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [_msg_to_openai(m) for m in messages],
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if options.temperature != 0.7:
            payload["temperature"] = options.temperature
        if options.top_p is not None:
            payload["top_p"] = options.top_p
        if options.max_tokens is not None:
            payload["max_tokens"] = options.max_tokens
        if options.stop:
            payload["stop"] = options.stop
        # 流式 usage 默认不返回，需显式开启；Ollama 等本地服务不支持该字段
        if not self._is_local_endpoint():
            payload["stream_options"] = {"include_usage": True}
        # 透传 extra
        for k, v in options.extra.items():
            payload[k] = v
        return payload

    def _is_local_endpoint(self) -> bool:
        """是否指向本地推理服务（Ollama / localhost）。

        这类服务通常不支持 `stream_options` 等云端扩展字段，需要跳过。
        """
        lowered = self.base_url.lower()
        return "ollama" in lowered or "localhost" in lowered or "127.0.0.1" in lowered

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    # ------------------------------------------------------------------
    # SSE 解析
    # ------------------------------------------------------------------

    async def _parse_sse(
        self, response: httpx.Response
    ) -> AsyncIterator[ChatChunk]:
        """逐行解析 OpenAI 兼容 SSE 流。

        SSE 里每一行以 `data: ` 开头；`data: [DONE]` 表示结束。
        """
        async for line in response.aiter_lines():
            line = line.strip()
            if not line or not line.startswith("data: "):
                continue
            body = line[len("data: "):].strip()
            if body == "[DONE]":
                return
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                continue
            yield self._sse_to_chunk(payload)

    def _sse_to_chunk(self, payload: dict[str, Any]) -> ChatChunk:
        """把一条 SSE payload 转成 ChatChunk。"""
        delta_text = ""
        tool_deltas: list[ToolCallDelta] = []
        finish_reason: str | None = None
        usage: Usage | None = None

        raw_usage = payload.get("usage")
        if raw_usage:
            usage = _parse_usage(raw_usage)

        choices = payload.get("choices", [])
        if choices:
            first = choices[0]
            finish_reason = first.get("finish_reason")
            inner = first.get("delta") or first.get("message") or {}
            delta_text = inner.get("content") or ""
            # 流式的 tool_calls 是增量切片
            for raw_tc in inner.get("tool_calls") or []:
                index = raw_tc.get("index", 0)
                func = raw_tc.get("function", {})
                tool_deltas.append(
                    ToolCallDelta(
                        index=index,
                        id=raw_tc.get("id"),
                        name=func.get("name"),
                        arguments_delta=func.get("arguments", "") or "",
                    )
                )

        return ChatChunk(
            delta=delta_text,
            tool_calls_delta=tool_deltas,
            finish_reason=finish_reason,
            usage=usage,
            raw=payload,
        )

    # ------------------------------------------------------------------
    # Model.stream 实现
    # ------------------------------------------------------------------

    async def stream(
        self,
        messages: list[Msg],
        tools: list[dict[str, Any]],
        options: GenerateOptions,
    ) -> AsyncIterator[ChatChunk]:
        """发 SSE 请求并逐块 yield ChatChunk。"""
        payload = self._build_payload(messages, tools, options)
        headers = self._build_headers()
        url = f"{self.base_url}/chat/completions"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", url, json=payload, headers=headers
            ) as response:
                response.raise_for_status()
                async for chunk in self._parse_sse(response):
                    yield chunk
