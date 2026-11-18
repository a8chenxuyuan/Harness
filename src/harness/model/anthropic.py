"""Anthropic Messages API 的模型适配器。

与 OpenAI 兼容接口的关键差异：

1. 消息格式不同：每条 message 的 content 是数组（支持多类型），role 只有
   user / assistant / system，system 是请求顶层字段而非 messages 里的一条。
2. 显式缓存通过 cache_control: {type: "ephemeral", ttl: "..."} 实现，需要
   插在 system 块末尾、messages 数组里选定位置、以及每个 tool 定义之后。
3. SSE 事件类型不同：event: content_block_delta 携带真正增量；
   event: message_start / message_delta / message_stop 携带 usage。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..message.msg import Msg
from .base import Model, ModelCapabilities
from .cache_profile import Breakpoint, CacheHints, CacheMode
from .types import ChatChunk, GenerateOptions, ToolCallDelta, Usage


def _msg_to_anthropic(msg: Msg) -> dict[str, Any]:
    """把 Msg 转成 Anthropic Messages API 的单条 message 格式。

    Returns:
        {"role": "user"|"assistant", "content": [{"type": "text", "text": "..."}]}
        格式的 dict。system 角色由调用方单独提取，不放进 messages。
    """
    role = msg.role.value
    text = msg.text()
    if role == "system":
        # system 块在 Anthropic 里要单独处理，调用方拆出来。
        return {"role": "system", "text": text}
    content: list[dict[str, Any]] = []
    if text:
        content.append({"type": "text", "text": text})
    return {"role": role, "content": content}


class AnthropicModel(Model):
    """Anthropic Messages API 适配器。

    Attributes:
        api_key: Anthropic API Key。
        model: 模型名，如 `claude-3-5-sonnet-20241022`。
        base_url: API 根地址，默认官方端点。
        timeout: 单次请求超时秒数。
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com",
        timeout: float = 30.0,
        capabilities: ModelCapabilities | None = None,
    ) -> None:
        self.api_key = api_key
        self.model_name = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        super().__init__(capabilities=capabilities)

    def detect_capabilities(self) -> ModelCapabilities:
        """Anthropic 官方 API：显式缓存 + 显式 tools + 流式 + 结构化输出。"""
        return ModelCapabilities(
            max_context_tokens=200_000,
            supports_tools=True,
            supports_cache_control=True,
            supports_structured_output=True,
            supports_streaming=True,
            cache_mode=CacheMode.EXPLICIT,
        )

    # ------------------------------------------------------------------
    # 构造请求体（含 cache_control 插入）
    # ------------------------------------------------------------------

    def _build_system(
        self, system_prompt: str, hints: CacheHints | None
    ) -> list[dict[str, Any]]:
        """system 块：纯文本 + 末尾 cache_control（如果有显式断点）。"""
        blocks: list[dict[str, Any]] = [{"type": "text", "text": system_prompt}]
        if hints and hints.prefix_cacheable and hints.mode is CacheMode.EXPLICIT:
            first = hints.breakpoints[0] if hints.breakpoints else None
            if first and first.after == "stable_prefix":
                blocks.append(
                    {"type": "cache_control", "cache_control": {"type": "ephemeral", "ttl": first.ttl or "1h"}}
                )
        return blocks

    def _build_messages(
        self, messages: list[Msg], hints: CacheHints | None
    ) -> tuple[list[dict[str, Any]], str]:
        """拆分 system 与其余消息，并按 Breakpoint 插 cache_control。

        Returns:
            (messages_body, system_prompt)：前者是 Anthropic 要的 messages 数组，
            后者是单独提出的 system 文本。
        """
        system_parts: list[str] = []
        rest: list[dict[str, Any]] = []
        for m in messages:
            if m.role.value == "system":
                system_parts.append(m.text())
            else:
                rest.append(_msg_to_anthropic(m))

        # 按 Breakpoint.after 在 history 末尾插 cache_control
        if hints and hints.prefix_cacheable and hints.mode is CacheMode.EXPLICIT:
            for bp in hints.breakpoints:
                if not bp.after.startswith("history[-"):
                    continue
                # 解析 offset：history[-N]
                offset_str = bp.after[len("history[-"):-1]
                try:
                    offset = int(offset_str)
                except ValueError:
                    continue
                if offset <= len(rest):
                    insert_at = len(rest) - offset + 1
                    rest.insert(
                        insert_at,
                        {
                            "type": "cache_control",
                            "cache_control": {"type": "ephemeral", "ttl": bp.ttl or "5m"},
                        },
                    )
        return rest, "\n".join(system_parts)

    def _build_tool_defs(
        self, tools: list[dict[str, Any]], hints: CacheHints | None
    ) -> list[dict[str, Any]]:
        """tools 定义列表；显式缓存时在每个 tool 后面也插 cache_control。"""
        out: list[dict[str, Any]] = list(tools)
        if hints and hints.prefix_cacheable and hints.mode is CacheMode.EXPLICIT:
            for _ in range(len(out)):
                out.append(
                    {
                        "type": "cache_control",
                        "cache_control": {"type": "ephemeral", "ttl": "1h"},
                    }
                )
        return out

    def _build_payload(
        self,
        messages: list[Msg],
        tools: list[dict[str, Any]],
        options: GenerateOptions,
    ) -> dict[str, Any]:
        hints: CacheHints | None = None
        if options.cache_profile_override is not None:
            # GenerateOptions.cache_profile_override 可能带 hints——
            # 为了保持基类简单，这里暂时不使用 override，沿用 hints=None。
            # 后续上层会话层会把 CacheHints 注入到 options.extra 里再捞出来。
            pass
        # 尝试从 extra 里捞上层塞的 cache_hints
        hints = options.extra.get("_cache_hints") if isinstance(options.extra.get("_cache_hints"), CacheHints) else None

        body_messages, system_prompt = self._build_messages(messages, hints)
        payload: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": options.max_tokens or 4096,
            "stream": True,
            "messages": body_messages,
        }
        if system_prompt:
            payload["system"] = self._build_system(system_prompt, hints)
        if tools:
            payload["tools"] = self._build_tool_defs(tools, hints)
        if options.temperature != 0.7:
            payload["temperature"] = options.temperature
        if options.stop:
            payload["stop_sequences"] = options.stop
        return payload

    def _build_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
        }

    # ------------------------------------------------------------------
    # SSE 解析（Anthropic 格式）
    # ------------------------------------------------------------------

    async def _parse_sse(
        self, response: httpx.Response
    ) -> AsyncIterator[ChatChunk]:
        """逐事件解析 Anthropic SSE 流。

        事件结构：
            event: content_block_delta
            data: {"type": "content_block_delta", "delta": {...}}
            event: message_start
            data: {"type": "message_start", "message": {"usage": {...}}}
            event: message_delta
            data: {"type": "message_delta", "usage": {...}, "stop_reason": "..."}
            event: message_stop
            data: {"type": "message_stop"}
        """
        event_name: str | None = None
        usage = Usage()

        async for raw_line in response.aiter_lines():
            line = raw_line.strip()
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
                continue
            if line.startswith("data:") and event_name is not None:
                body = line[len("data:"):].strip()
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    continue

                if event_name == "message_start":
                    u = (payload.get("message") or {}).get("usage", {})
                    usage.prompt_tokens = u.get("input_tokens", 0)
                    usage.cache_read_tokens = u.get("cache_read_input_tokens", 0) or 0
                elif event_name == "message_delta":
                    u = payload.get("usage", {})
                    usage.completion_tokens = u.get("output_tokens", 0)
                    stop_reason = payload.get("stop_reason")
                    if stop_reason is not None:
                        yield ChatChunk(
                            finish_reason=stop_reason,
                            usage=usage,
                            raw=payload,
                        )
                elif event_name == "content_block_delta":
                    delta = payload.get("delta", {})
                    delta_text = delta.get("text") or ""
                    tool_deltas: list[ToolCallDelta] = []
                    if delta.get("type") == "input_json_delta":
                        # 工具调用 arguments 的分段 JSON
                        tool_deltas.append(
                            ToolCallDelta(
                                index=delta.get("index", 0),
                                arguments_delta=delta.get("partial_json", "") or "",
                            )
                        )
                    elif delta.get("type") == "text_delta":
                        delta_text = delta.get("text", "") or ""
                    if delta_text or tool_deltas:
                        yield ChatChunk(
                            delta=delta_text,
                            tool_calls_delta=tool_deltas,
                            raw=payload,
                        )
                    # 也可能是 thinking_delta 等，目前忽略
                # message_stop 事件空 data，不处理

                event_name = None
                continue
            # 空行或心跳，忽略

    # ------------------------------------------------------------------
    # Model.stream 实现
    # ------------------------------------------------------------------

    async def stream(
        self,
        messages: list[Msg],
        tools: list[dict[str, Any]],
        options: GenerateOptions,
    ) -> AsyncIterator[ChatChunk]:
        """发 POST /v1/messages 并逐块 yield ChatChunk。"""
        payload = self._build_payload(messages, tools, options)
        headers = self._build_headers()
        url = f"{self.base_url}/v1/messages"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", url, json=payload, headers=headers
            ) as response:
                response.raise_for_status()
                async for chunk in self._parse_sse(response):
                    yield chunk
