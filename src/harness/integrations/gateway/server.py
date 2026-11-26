"""Gateway HTTP + WebSocket server（Phase 12 - GatewayServer）。

⚠️ 本文件已瘦身。所有 REST 路由已迁到 :mod:`harness.platform.api.controllers`，
GatewayServer 只做两件事：

1. :func:`build_app` —— 调 ``harness.app.create_app()`` 构造 FastAPI 实例，
   再注入 GatewayRouter + adapter；
2. :class:`GatewayServer` —— 便捷 facade：auto_register_adapters + uvicorn.start。

**依赖降级**：
    - FastAPI / uvicorn 没装时 ``build_app`` 会抛 ConfigurationError
    - Feishu / McpStdio 配置缺失时不注册对应 adapter，server 照常启动

**调用链**：
    GatewayServer.build() → build_app() → harness.app.create_app() + 注入 router
    GatewayServer.start() → uvicorn.run(app)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

from .adapters.feishu import ConfigurationError  # noqa: E402
from .router import GatewayRouter  # noqa: E402


def _is_fastapi_available() -> bool:
    try:
        import fastapi  # noqa: F401
        return True
    except ImportError:
        return False


_FASTAPI_AVAILABLE = _is_fastapi_available()


# ---------------------------------------------------------------------------
# build_app：构造 FastAPI 实例（内部委托 harness.app.create_app）
# ---------------------------------------------------------------------------


def build_app(
    router: GatewayRouter | None = None,
    hitl_manager: Any | None = None,
    app_settings: dict[str, Any] | None = None,
) -> Any:
    """构建 FastAPI 应用。

    内部调 :func:`harness.app.create_app`，然后把 GatewayRouter + adapters
    绑到 ``app.state`` 和 ``harness.platform.api.deps`` 的单例上。

    Args:
        router: GatewayRouter 实例（可选，不传时内部创建一个空的）。
        hitl_manager: HitlManager 实例（可选，保持兼容）。
        app_settings: 给 lifespan 用的配置字典。

    Returns:
        FastAPI 实例。

    Raises:
        ConfigurationError: FastAPI 未安装。
    """
    if not _FASTAPI_AVAILABLE:
        raise ConfigurationError(
            "FastAPI/Pydantic 未安装，无法启动 GatewayServer。"
            "请 pip install fastapi pydantic。"
        )

    from harness.app import create_app
    from harness.platform.api.deps import set_gateway_router

    router = router or GatewayRouter()
    settings = app_settings or {"service_name": "harness", "version": "0.1.0"}

    # 用统一的应用工厂
    app = create_app()

    # 注入 GatewayRouter（让 api/v1/gateway.py 的 get_gateway_router 拿到）
    set_gateway_router(router)

    # 保留 app.state 上的引用（旧代码可能直接访问）
    app.state.router = router
    app.state.hitl_manager = hitl_manager
    app.state.settings = settings
    app.state.agent_runner = None

    return app


# ---------------------------------------------------------------------------
# GatewayServer 便捷 facade
# ---------------------------------------------------------------------------


class GatewayServer:
    """把 router + adapters + FastAPI app 绑在一起的便捷 facade。

    典型用法::

        server = GatewayServer(config)
        server.build()
        await server.start(host="0.0.0.0", port=8000, agent_runner=my_runner)
    """

    def __init__(
        self,
        gateway_config: dict[str, Any] | None = None,
    ) -> None:
        self.config = dict(gateway_config) if gateway_config else {}
        self.router = GatewayRouter()
        self.app: Any | None = None
        self._tasks: list[asyncio.Task[Any]] = []

    # ------------------------------------------------------------------
    # adapter 注册
    # ------------------------------------------------------------------

    def auto_register_adapters(self) -> None:
        """根据 config 里的各 channel 子配置自动注册可用 adapter。

        Feishu / McpStdio 配置缺失时跳过，WebChat 总是注册。
        """
        from .adapters import FeishuAdapter, McpStdioAdapter, WebChatAdapter

        # WebChat（无配置）
        webchat = WebChatAdapter()
        self.router.register(webchat)

        # Feishu
        feishu_cfg = self.config.get("feishu") or {}
        feishu = FeishuAdapter(feishu_cfg)
        if feishu.ready_for_use:
            self.router.register(feishu)
        else:
            log.info("Gateway: feishu config 缺失，跳过注册")

        # McpStdio
        mcp_cfg = self.config.get("mcp_stdio") or {}
        mcp = McpStdioAdapter(mcp_cfg)
        if mcp.ready_for_use:
            self.router.register(mcp)
        else:
            log.info("Gateway: mcp_stdio config 缺失，跳过注册")

    # ------------------------------------------------------------------
    # 构建 & 启动
    # ------------------------------------------------------------------

    def build(self, *, hitl_manager: Any = None) -> Any:
        """构造 FastAPI 应用。

        Args:
            hitl_manager: 可选的 HitlManager。

        Returns:
            FastAPI 实例。
        """
        if not self.router.adapters:
            self.auto_register_adapters()
        self.app = build_app(self.router, hitl_manager=hitl_manager, app_settings=self.config)
        return self.app

    def set_agent_runner(self, runner: Any) -> None:
        """注入 Agent 处理函数。

        Args:
            runner: callable，签名 ``async def (RawMessage) -> str | AsyncIterator[str]``。
        """
        if self.app is not None:
            self.app.state.agent_runner = runner

    async def start(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8000,
        agent_runner: Any = None,
    ) -> None:
        """启动 uvicorn。

        Args:
            host: 监听地址。
            port: 监听端口。
            agent_runner: 可选，注入后再启动。
        """
        if self.app is None:
            self.build()
        if agent_runner is not None:
            self.set_agent_runner(agent_runner)

        try:
            import uvicorn
        except ImportError as exc:
            raise ConfigurationError("uvicorn 未安装，无法启动 GatewayServer.start()") from exc

        log.info("Gateway: 启动 uvicorn on %s:%d", host, port)
        config = uvicorn.Config(self.app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()
