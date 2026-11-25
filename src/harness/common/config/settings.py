"""Harness 全局配置（pydantic-settings ≥ 2.2）。

三类配置层级：

- :class:`ModelSettings` —— 大模型供应商标识、base_url、api_key、模型名。
- :class:`GatewaySettings` —— WebChat 监听 + 飞书 / MCP stdio 适配器配置。
- :class:`Settings` —— 总装配点，同时暴露 OTel endpoint 与 Prometheus 端口。

所有字段都有安全缺省：没填 api_key 时代理会自动降级（examples 会 graceful skip），
OTel / Gateway 子模块不启用时就是 no-op，保证 Harness 在「零配置」下也能 import 通过。

文件只负责「数据 + 从 .env 加载」，不做任何 I/O；与 observability / gateway /
model 的实际初始化在各自子包里完成。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModelSettings(BaseModel):
    """大模型供应商标识与认证信息。

    Attributes:
        provider: 供应商标识，覆盖 deepseek / openai / anthropic / kimi / ollama
            等。值会被 model.openai_compat / model.anthropic 用来决定默认 model。
        base_url: 供应商 API 根地址。空串表示走 SDK 缺省值（如 Anthropic 官方、
            OpenAI 官方）；自建或第三方兼容端点（如 Ollama、硅基流动）需显式填。
        api_key: API Key。缺省时 examples / benchmarks 会 graceful skip；
            真实 gateway 收到无 key 时直接报错返回 401。
        model: 模型名（如 deepseek-chat、gpt-4o-mini、claude-3-5-sonnet-latest）。
            空串时由 provider 推断一个合理默认值。
    """

    model_config = ConfigDict(extra="forbid")

    provider: str = "deepseek"
    base_url: str = ""
    api_key: str = ""
    model: str = ""

    def has_credentials(self) -> bool:
        """是否配置了可工作的凭据（用于 examples 判断是否 skip）。"""
        return bool(self.api_key)


class GatewaySettings(BaseModel):
    """Gateway 层的网络与适配器配置。

    Attributes:
        host: WebChat / 内部 HTTP 监听地址；容器化时用 0.0.0.0。
        port: WebChat / 内部 HTTP 监听端口。
        feishu: 飞书机器人配置 dict。含 app_id / app_secret / verify_token
            三个键；空 dict 表示适配器不启用。
        mcp: MCP stdio 子进程配置 dict。含 command / args 两个键；
            空 dict 表示不启动 MCP client。
    """

    model_config = ConfigDict(extra="forbid")

    host: str = "0.0.0.0"
    port: int = 8765
    feishu: dict[str, Any] = Field(default_factory=dict)
    mcp: dict[str, Any] = Field(default_factory=dict)

    @property
    def feishu_enabled(self) -> bool:
        """feishu 适配器是否可以被加载。"""
        return bool(self.feishu.get("app_id")) and bool(self.feishu.get("app_secret"))

    @property
    def mcp_enabled(self) -> bool:
        """MCP stdio client 是否可以启动。"""
        return bool(self.mcp.get("command"))


class Settings(BaseModel):
    """Harness 全局配置入口。

    ``BaseSettings`` 在 pydantic-settings ≥ 2.2 里是 :class:`BaseModel` 的子类，
    构造时会从环境变量 + ``.env`` 文件加载同名（大写）字段；嵌套模型则用
    ``MODEL__API_KEY`` 这种双下划线风格。

    Attributes:
        model: 大模型配置。
        gateway: Gateway 层配置。
        otlp_endpoint: OpenTelemetry OTLP gRPC / HTTP endpoint。空串表示 tracing
            走 no-op span。
        prometheus_port: Prometheus HTTP exporter 端口。
        api_host / api_port: FastAPI 监听地址 / 端口。
        database_url: 数据库连接串。空串时 db.engine 回退到默认 SQLite 文件。
        jwt_secret: JWT HS256 签名密钥。生产必须覆盖，空串走内置 dev secret。
        cors_origins: CORS 允许的来源列表。
        dev_mode: 开发模式开关。True 时无 token 的请求按 dev-tenant owner 放行；
            生产必须保持 False（env ``HARNESS_DEV_MODE``）。
    """

    model_config = ConfigDict(extra="forbid")

    # --- 已有 ---
    model: ModelSettings = Field(default_factory=ModelSettings)
    gateway: GatewaySettings = Field(default_factory=GatewaySettings)
    otlp_endpoint: str = ""
    prometheus_port: int = 9700

    # --- Phase 22 新增 ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str = ""
    jwt_secret: str = ""
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    dev_mode: bool = False

    # --- 便捷查询 ---------------------------------------------------------------

    def has_model_credentials(self) -> bool:
        """与 ModelSettings.has_credentials 对称，方便 Agent / Example 快速判断。"""
        return self.model.has_credentials()


# ---------------------------------------------------------------------------
# pydantic-settings 接入（延迟 import 避免未装时阻断）
# ---------------------------------------------------------------------------

def _build_settings_class():
    """动态把 Settings 升级为 :class:`pydantic_settings.BaseSettings` 子类。

    pydantic-settings 未安装时回退到普通 BaseModel（环境变量不生效，
    但字段依然有合理默认值），保证 import 不炸。
    """
    try:
        from pydantic_settings import BaseSettings, SettingsConfigDict
    except ImportError:  # pragma: no cover - 环境缺依赖
        return Settings

    class _LazySettings(BaseSettings, Settings):
        """延迟构造的 Settings，支持 .env / env 变量。"""

        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            env_prefix="HARNESS_",
            extra="forbid",
            env_nested_delimiter="__",
        )

    _LazySettings.__name__ = "Settings"
    return _LazySettings


# 对外始终暴露 Settings（导入时已完成升级 / 回退）
Settings = _build_settings_class()
