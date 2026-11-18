"""Harness 配置模块（edge）。

对外暴露三个 Pydantic Settings / Model 类，以及一个便捷的 :func:`load`
函数（直接构造 Settings，会自动从 ``.env`` + 环境变量读取）。

>>> from harness.config import Settings, load
>>> s = load()
>>> s.model.provider
'deepseek'
"""

from .settings import GatewaySettings, ModelSettings, Settings

__all__ = [
    "GatewaySettings",
    "ModelSettings",
    "Settings",
]


def load(**overrides) -> Settings:
    """构造一个 Settings 实例，允许用 keyword 覆盖。

    Args:
        **overrides: 任何字段覆盖，比如 ``load(model__provider="openai")``
            （pydantic-settings 的 env_nested_delimiter 是双下划线）。

    Returns:
        填好的 Settings。
    """
    return Settings(**overrides)
