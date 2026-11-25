"""模型与工具的构造入口。

统一从 ``Settings`` 读取模型配置，配置项见仓库根 ``.env.example``：

    HARNESS_MODEL__PROVIDER   deepseek / openai / anthropic / kimi / ollama
    HARNESS_MODEL__BASE_URL   OpenAI 兼容端点
    HARNESS_MODEL__API_KEY    凭据（ollama 可空）
    HARNESS_MODEL__MODEL      模型名

缺凭据时抛 ``ModelConfigError``，不做「假装成功」的降级。
"""

from __future__ import annotations

from typing import Any

DEFAULT_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
    "kimi": "https://api.moonshot.cn/v1",
}

DEFAULT_MODELS: dict[str, str] = {
    "deepseek": "deepseek-chat",
    "openai": "gpt-4o-mini",
    "kimi": "kimi-k2-0905-preview",
    "anthropic": "claude-3-5-sonnet-latest",
    "ollama": "qwen2.5:7b",
}


class ModelConfigError(RuntimeError):
    """模型配置缺失或不可用。"""


def build_default_model() -> Any:
    """按 Settings 构造模型适配器。"""
    from harness.common.config.settings import Settings

    cfg = Settings().model
    provider = (cfg.provider or "deepseek").strip().lower()
    model_name = (cfg.model or "").strip() or DEFAULT_MODELS.get(provider, "")
    if not model_name:
        raise ModelConfigError("模型名未配置：请填写 HARNESS_MODEL__MODEL")

    if provider != "ollama" and not cfg.api_key:
        raise ModelConfigError(
            "模型凭据未配置：请在 .env 填写 HARNESS_MODEL__API_KEY（示例见 .env.example）"
        )

    if provider == "anthropic":
        from harness.core.model.anthropic import AnthropicModel

        return AnthropicModel(
            api_key=cfg.api_key,
            model=model_name,
            base_url=cfg.base_url or "https://api.anthropic.com",
        )

    base_url = (cfg.base_url or DEFAULT_BASE_URLS.get(provider, "")).strip()
    if not base_url:
        raise ModelConfigError(
            f"未知 provider={provider}：请显式配置 HARNESS_MODEL__BASE_URL"
        )
    from harness.core.model.openai_compat import OpenAICompat

    return OpenAICompat(
        base_url=base_url,
        api_key=cfg.api_key or None,
        model=model_name,
    )


def build_default_tools() -> Any:
    """构造默认工具注册表（读文件 / 写文件 / Bash / HTTP GET）。"""
    from harness.core.tool.builtin import (
        BashTool,
        HttpGetTool,
        ReadFileTool,
        WriteFileTool,
    )
    from harness.core.tool.registry import ToolRegistry

    tools = ToolRegistry()
    for tool in (ReadFileTool(), WriteFileTool(), BashTool(), HttpGetTool()):
        tools.register(tool)
    return tools


__all__ = [
    "DEFAULT_BASE_URLS",
    "DEFAULT_MODELS",
    "ModelConfigError",
    "build_default_model",
    "build_default_tools",
]
