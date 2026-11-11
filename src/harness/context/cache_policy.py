"""供应商缓存画像与缓存断点策略。

唯一职责：把「这家供应商怎么缓存」翻译成装配器能直接用的断点列表。

为什么不放在 model/ 下：
    装配器在调模型之前就要决定断点，若依赖 model 包会形成反向依赖
    （Phase 2 不能引入 Phase 3 的模块）。画像在这里只描述能力，不碰传输层。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class CacheMode(str, Enum):
    """供应商的缓存实现方式。

    Attributes:
        EXPLICIT: 需要显式打断点（cache_control），如 Anthropic。
        AUTOMATIC: 供应商自动按前缀命中，传参无用，如 DeepSeek / OpenAI。
        NONE: 无前缀缓存能力，如部分本地部署。
    """

    EXPLICIT = "explicit"
    AUTOMATIC = "automatic"
    NONE = "none"


class Breakpoint(BaseModel):
    """一个缓存断点。

    Attributes:
        after: 断点位置，`stable_prefix` 或 `history[-N]`。
        ttl: 缓存存活时长档位；供应商不支持时为 None。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    after: str
    ttl: str | None = None


class CacheHints(BaseModel):
    """装配器产出的缓存提示，交给模型适配层原样使用。

    Attributes:
        provider: 画像对应的供应商名。
        mode: 缓存方式。
        breakpoints: 显式断点；自动缓存时为空。
        prompt_cache_key: 自动缓存供应商的会话级稳定键。
        prefix_cacheable: 当前前缀长度是否达到该供应商的最小可缓存长度。
        min_cacheable_tokens: 该供应商的最小可缓存长度，便于上层解释未命中原因。
    """

    model_config = ConfigDict(extra="forbid")

    provider: str
    mode: CacheMode
    breakpoints: list[Breakpoint] = Field(default_factory=list)
    prompt_cache_key: str | None = None
    prefix_cacheable: bool = False
    min_cacheable_tokens: int = 0


class CacheProfile(BaseModel):
    """供应商缓存能力画像，是装配器的输入。

    Attributes:
        provider: 供应商标识。
        mode: 缓存方式。
        min_cacheable_tokens: 低于此长度不承诺命中。
        max_breakpoints: 显式断点上限；自动缓存为 0。
        ttl_options: 支持的 TTL 档位。
        default_ttl: 缺省选用的 TTL。
        reports_cache_usage: 是否返回 cache_read_tokens。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    mode: CacheMode
    min_cacheable_tokens: int
    max_breakpoints: int = 0
    ttl_options: tuple[str, ...] = ()
    default_ttl: str | None = None
    reports_cache_usage: bool = False


CACHE_PROFILES: dict[str, CacheProfile] = {
    "anthropic": CacheProfile(
        provider="anthropic",
        mode=CacheMode.EXPLICIT,
        min_cacheable_tokens=1024,
        max_breakpoints=4,
        ttl_options=("5m", "1h"),
        default_ttl="1h",
        reports_cache_usage=True,
    ),
    "openai": CacheProfile(
        provider="openai",
        mode=CacheMode.AUTOMATIC,
        min_cacheable_tokens=1024,
        max_breakpoints=0,
        reports_cache_usage=True,
    ),
    "deepseek": CacheProfile(
        provider="deepseek",
        mode=CacheMode.AUTOMATIC,
        min_cacheable_tokens=64,
        max_breakpoints=0,
        reports_cache_usage=False,
    ),
    "ollama": CacheProfile(
        provider="ollama",
        mode=CacheMode.NONE,
        min_cacheable_tokens=0,
        max_breakpoints=0,
        reports_cache_usage=False,
    ),
}
"""内置画像。OpenAI 兼容的国产供应商共用 automatic 画像，按需在调用方覆盖。"""

_PROVIDER_ALIASES: dict[str, str] = {
    "claude": "anthropic",
    "gpt": "openai",
    "qwen": "openai",
    "dashscope": "openai",
    "tongyi": "openai",
    "kimi": "openai",
    "moonshot": "openai",
    "glm": "openai",
    "zhipu": "openai",
    "doubao": "openai",
    "volcengine": "openai",
    "local": "ollama",
    "vllm": "ollama",
}


def profile_for(provider: str) -> CacheProfile:
    """按供应商名取缓存画像。

    Args:
        provider: 供应商标识，大小写与首尾空格不敏感。

    Returns:
        已知供应商返回内置画像；未知供应商返回一份保守的 automatic 画像，
        保证「不认识的供应商也不会被强行打断点」。
    """
    normalized = provider.strip().lower()
    key = _PROVIDER_ALIASES.get(normalized, normalized)
    known = CACHE_PROFILES.get(key)
    if known is not None:
        return known
    return CacheProfile(
        provider=normalized,
        mode=CacheMode.AUTOMATIC,
        min_cacheable_tokens=1024,
        max_breakpoints=0,
        reports_cache_usage=False,
    )


def build_cache_hints(
    profile: CacheProfile,
    prefix_tokens: int,
    session_id: str,
    history_length: int,
    ttl: str | None = None,
) -> CacheHints:
    """按画像生成本轮缓存提示。

    Args:
        profile: 供应商缓存画像。
        prefix_tokens: 稳定前缀的 token 数。
        session_id: 会话标识，自动缓存供应商用它做 prompt_cache_key。
        history_length: 历史消息条数，显式断点会挂在最近两条上。
        ttl: 指定 TTL；为 None 时用画像缺省值。

    Returns:
        本轮的缓存提示。前缀未达最小可缓存长度时不下发任何断点，
        避免给出「看起来在省 token」的假象。
    """
    cacheable = profile.mode is not CacheMode.NONE and (
        prefix_tokens >= profile.min_cacheable_tokens
    )
    hints = CacheHints(
        provider=profile.provider,
        mode=profile.mode,
        prefix_cacheable=cacheable,
        min_cacheable_tokens=profile.min_cacheable_tokens,
    )
    if not cacheable:
        return hints

    if profile.mode is CacheMode.EXPLICIT:
        chosen_ttl = ttl or profile.default_ttl
        breakpoints = [Breakpoint(after="stable_prefix", ttl=chosen_ttl)]
        for offset in range(1, min(2, history_length) + 1):
            if len(breakpoints) >= profile.max_breakpoints:
                break
            breakpoints.append(Breakpoint(after=f"history[-{offset}]", ttl="5m"))
        hints.breakpoints = breakpoints
    elif profile.mode is CacheMode.AUTOMATIC:
        hints.prompt_cache_key = session_id

    return hints
