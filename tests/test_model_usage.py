"""模型层的上下文窗口与 token 计量单测（全部离线，不发真实请求）。"""

from __future__ import annotations

from harness.core.loop.state import AgentState
from harness.core.model.openai_compat import (
    OpenAICompat,
    _infer_context_window,
    _parse_usage,
)
from harness.core.model.types import ChatChunk, GenerateOptions, Usage, merge_usage


def _make_model(base_url: str = "https://api.deepseek.com/v1") -> OpenAICompat:
    """构造一个 OpenAI 兼容模型实例（不发起请求）。"""
    return OpenAICompat(base_url=base_url, api_key="test-key", model="deepseek-flash")


def test_context_window_by_model_name() -> None:
    """DeepSeek V4 系列按 1M 上下文，未知模型退回 32k。"""
    assert _infer_context_window("deepseek-flash") == 1_048_576
    assert _infer_context_window("deepseek-v4-pro") == 1_048_576
    assert _infer_context_window("deepseek-v4-preview") == 1_048_576
    assert _infer_context_window("deepseek-chat") == 128_000
    assert _infer_context_window("some-unknown-model") == 32_000


def test_capabilities_use_model_context_window() -> None:
    """能力探测结果应带上模型真实的上下文窗口。"""
    assert _make_model().capabilities.max_context_tokens == 1_048_576
    assert (
        _make_model("http://localhost:11434/v1").capabilities.max_context_tokens
        == 1_048_576
    )


def test_parse_usage_supports_deepseek_and_openai_fields() -> None:
    """DeepSeek 的 prompt_cache_hit_tokens 与 OpenAI 的 cached_tokens 都要识别。"""
    deepseek = _parse_usage(
        {
            "prompt_tokens": 36,
            "completion_tokens": 68,
            "total_tokens": 104,
            "prompt_cache_hit_tokens": 12,
        }
    )
    assert deepseek == Usage(
        prompt_tokens=36,
        completion_tokens=68,
        total_tokens=104,
        cache_read_tokens=12,
    )

    openai = _parse_usage(
        {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "prompt_tokens_details": {"cached_tokens": 4},
        }
    )
    assert openai.total_tokens == 15
    assert openai.cache_read_tokens == 4


def test_sse_chunk_parses_usage_block() -> None:
    """流末尾的 usage 块要能解析进 ChatChunk。"""
    chunk = _make_model()._sse_to_chunk(
        {
            "choices": [],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 8,
                "total_tokens": 28,
                "prompt_cache_hit_tokens": 6,
            },
        }
    )
    assert chunk.usage is not None
    assert chunk.usage.total_tokens == 28
    assert chunk.usage.cache_read_tokens == 6


def test_build_payload_enables_stream_usage_for_cloud_endpoint() -> None:
    """云端兼容端点要带 stream_options；本地端点不带。"""
    cloud = _make_model()._build_payload([], [], GenerateOptions())
    assert cloud["stream_options"] == {"include_usage": True}

    local = _make_model("http://localhost:11434/v1")._build_payload(
        [], [], GenerateOptions()
    )
    assert "stream_options" not in local


def test_merge_usage_takes_max_per_field() -> None:
    """同一轮多块上报时按字段取最大值，而不是相加。"""
    merged = merge_usage(
        Usage(prompt_tokens=10, completion_tokens=0, total_tokens=10),
        Usage(prompt_tokens=10, completion_tokens=7, total_tokens=17),
    )
    assert merged.prompt_tokens == 10
    assert merged.completion_tokens == 7
    assert merged.total_tokens == 17


def test_agent_state_accumulates_usage() -> None:
    """AgentState 要按轮累加，并通过 metrics 暴露给运行记录。"""
    state = AgentState(session_id="sess-usage")
    state.add_usage(Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15))
    state.add_usage(
        Usage(prompt_tokens=3, completion_tokens=2, total_tokens=5, cache_read_tokens=1)
    )

    assert state.metrics == {
        "prompt_tokens": 13,
        "completion_tokens": 7,
        "total_tokens": 20,
        "cache_read_tokens": 1,
    }


def test_chat_chunk_accepts_usage() -> None:
    """ChatChunk 必须接受 usage 参数（Anthropic 适配器依赖它）。"""
    chunk = ChatChunk(usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2))
    assert chunk.usage is not None
    assert chunk.usage.total_tokens == 2
