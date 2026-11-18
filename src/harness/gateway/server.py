"""Gateway FastAPI server（Phase 12 - GatewayServer）。

用 ``build_app`` 构造一个完整的 FastAPI 应用，然后 ``GatewayServer``
类把 router + server + adapters 绑在一起。

**依赖降级**：
  - FastAPI / uvicorn 没装时 ``build_app`` 会抛 ConfigurationError
  - Feishu / McpStdio 配置缺失时不注册对应 adapter，server 照常启动
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

log = logging.getLogger(__name__)

# 共享 ConfigurationError（与 adapters 共用）
from .adapters.feishu import ConfigurationError  # noqa: E402
from .router import GatewayRouter

# ---------------------------------------------------------------------------
# 依赖检测
# ---------------------------------------------------------------------------


def _is_fastapi_available() -> bool:
    try:
        import fastapi  # noqa: F401
        import pydantic  # noqa: F401
        return True
    except ImportError:
        return False


_FASTAPI_AVAILABLE = _is_fastapi_available()


# ---------------------------------------------------------------------------
# build_app：构造 FastAPI 实例
# ---------------------------------------------------------------------------


def build_app(
    router: Any | None = None,
    hitl_manager: Any | None = None,
    app_settings: dict[str, Any] | None = None,
) -> Any:
    """构建 FastAPI 应用。

    Args:
        router: GatewayRouter 实例（可选，不传时内部创建一个空的）。
        hitl_manager: HitlManager 实例（可选）。
        app_settings: 给 lifespan 用的配置字典（如 {"service_name": "harness"}）。

    Returns:
        FastAPI 实例。

    Raises:
        ConfigurationError: FastAPI/Pydantic 未安装。
    """
    if not _FASTAPI_AVAILABLE:
        raise ConfigurationError(
            "FastAPI/Pydantic 未安装，无法启动 GatewayServer。"
            "请 pip install fastapi pydantic。"
        )

    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.responses import JSONResponse

    from harness.hitl import HitlManager
    from harness.observability import expose_dict, init_otel
    from harness.observability.logging import init_logging

    from .channel import RawMessage
    from .router import GatewayRouter
    from .steering_api import steer

    router = router or GatewayRouter()
    hitl_manager = hitl_manager or HitlManager()
    settings = app_settings or {"service_name": "harness", "version": "0.1.0"}

    # 保存全局引用（供 WebSocket / steer endpoint 访问）
    app_state: dict[str, Any] = {
        "router": router,
        "hitl_manager": hitl_manager,
        "settings": settings,
        "agent_runner": None,  # 由外部 set_agent_runner 注入
    }

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: D401 - lifespan 无需 doc
        # startup
        init_logging()
        init_otel(service_name=settings.get("service_name", "harness"))
        log.info("Gateway server startup: adapters=%s", list(router.adapters.keys()))
        yield
        # shutdown：清理 adapter
        for name, adapter in router.adapters.items():
            _cleanup_adapter(name, adapter)
        log.info("Gateway server shutdown complete")

    app = FastAPI(title="Harness Gateway", version=settings.get("version", "0.1.0"), lifespan=lifespan)

    # 把 router / state 绑到 app.state
    app.state.router = router
    app.state.hitl_manager = hitl_manager
    app.state.settings = settings
    app.state.agent_runner = None

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({
            "status": "ok",
            "version": settings.get("version", "0.1.0"),
        })

    @app.get("/metrics")
    async def metrics() -> JSONResponse:
        return JSONResponse(expose_dict())

    @app.post("/api/steer")
    async def api_steer(body: dict[str, Any]) -> JSONResponse:
        """中途插话：interrupt / continue / inject。"""
        # 延迟导入，避免 pydantic v1/v2 差异影响顶层
        from .steering_api import SteerRequest
        try:
            req = SteerRequest.model_validate(body)  # pydantic v2
        except AttributeError:
            req = SteerRequest.parse_obj(body)  # pydantic v1 fallback
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid request: {exc}") from exc

        result = await steer(req)
        if result is None:
            raise HTTPException(status_code=404, detail=f"session {req.session_id} not found")
        return JSONResponse({
            "ok": True,
            "result": result,
        })

    @app.post("/api/hitl/approve")
    async def hitl_approve(body: dict[str, Any]) -> JSONResponse:
        request_id = body.get("request_id")
        reason = body.get("reason", "approved")
        if not request_id:
            raise HTTPException(status_code=400, detail="request_id required")
        try:
            session = await hitl_manager.approve(request_id, reason=reason)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"session {request_id} not found")
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return JSONResponse({"ok": True, "status": session.status})

    @app.post("/api/hitl/deny")
    async def hitl_deny(body: dict[str, Any]) -> JSONResponse:
        request_id = body.get("request_id")
        reason = body.get("reason", "denied")
        if not request_id:
            raise HTTPException(status_code=400, detail="request_id required")
        try:
            session = await hitl_manager.deny(request_id, reason=reason)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"session {request_id} not found")
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return JSONResponse({"ok": True, "status": session.status})

    # ------------------------------------------------------------------
    # WebSocket /ws/chat
    # ------------------------------------------------------------------

    @app.websocket("/ws/chat")
    async def ws_chat(ws: WebSocket) -> None:
        from .adapters.webchat import WebChatAdapter, parse_ws_message

        await ws.accept()

        # 找 WebChatAdapter
        webchat = router.adapters.get("webchat")
        if webchat is None or not isinstance(webchat, WebChatAdapter):
            try:
                await ws.send_text("channel webchat 未注册")
            except Exception:  # noqa: BLE001
                pass
            await ws.close()
            return

        # 取 user_id：query param > 合成
        user_id = (
            ws.query_params.get("user_id")
            or f"{ws.client.host}:{ws.client.port}"
        )
        webchat.bind_ws(user_id, ws)
        log.info("ws/chat connected user=%s", user_id)

        try:
            while True:
                raw_text = await ws.receive_text()
                raw = await parse_ws_message(raw_text, user_id)
                # 用 router.dispatch
                agent_runner = _get_agent_runner(app_state)
                if agent_runner is None:
                    await ws.send_text("agent_runner not configured")
                    continue

                result = await router.dispatch(raw, agent_runner)
                if not result.ok:
                    log.warning("ws/chat dispatch failed: %s", result.error)
        except WebSocketDisconnect:
            log.info("ws/chat disconnected user=%s", user_id)
        except Exception:  # noqa: BLE001
            log.exception("ws/chat 异常")
        finally:
            webchat.unbind_ws(user_id)

    return app


# ---------------------------------------------------------------------------
# GatewayServer 包装类
# ---------------------------------------------------------------------------


class GatewayServer:
    """把 router + FastAPI app + adapters 绑在一起的便捷 facade。

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
    # adapter 注册（壳适配器）
    # ------------------------------------------------------------------

    def auto_register_adapters(self) -> None:
        """根据 config 里的各 channel 子配置自动注册可用 adapter。

        Feishu / McpStdio 配置缺失时跳过，WebChat 总是注册。
        """
        from .adapters import FeishuAdapter, McpStdioAdapter, WebChatAdapter

        # 1. WebChat（无配置）
        webchat = WebChatAdapter()
        self.router.register(webchat)

        # 2. Feishu（配置驱动）
        feishu_cfg = self.config.get("feishu") or {}
        feishu = FeishuAdapter(feishu_cfg)
        if feishu.ready_for_use:
            self.router.register(feishu)
        else:
            log.info("Gateway: feishu config 缺失，跳过注册")

        # 3. McpStdio（配置驱动）
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
        """构造 FastAPI 应用（不注册 adapter 的调用者需要手动 register）。

        Args:
            hitl_manager: 可选的 HitlManager。

        Returns:
            FastAPI 实例。

        Raises:
            ConfigurationError: FastAPI/Pydantic 未安装。
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
        """启动 uvicorn（需要 uvicorn 依赖）。

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


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _get_agent_runner(app_state: dict[str, Any]) -> Any:
    return app_state.get("agent_runner")


def _cleanup_adapter(name: str, adapter: Any) -> None:
    """关闭 adapter 的外部资源（如 McpStdio subprocess）。"""
    try:
        if hasattr(adapter, "stop"):
            # stop 可能是 coroutine —— 但 lifespan 是 async，这里调就 asyncio.create_task
            import inspect
            if inspect.iscoroutinefunction(adapter.stop):
                asyncio.create_task(adapter.stop())
            else:
                adapter.stop()
    except Exception:  # noqa: BLE001
        log.warning("Gateway: adapter %s 清理失败", name, exc_info=True)
