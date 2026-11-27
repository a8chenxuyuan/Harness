"""Harness 应用工厂（对应 Java 的 Application.java）。

职责：
    1. 构造 FastAPI 实例
    2. 挂中间件（CORS）
    3. 挂载 API Controller 路由 + Gateway WebSocket
    4. 注册 lifespan（init_db / observability / close_db）
    5. 注册统一异常处理

不做任何业务逻辑。Phase 0-21 引擎层的 import 路径保持原样不变。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """构造 FastAPI 应用实例。

    Returns:
        完整配置好的 FastAPI 实例，可直接传给 uvicorn.run(app)。
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # ===== startup =====
        _init_observability()
        await _init_db()
        # 依赖 init_db 之后执行：把重启前遗留的 running / streaming 收敛到终态
        await _recover_interrupted()
        # W4-CHAN-03：启动 Webhook 事件推送调度器（订阅 EventBus，失败不阻断启动）
        _start_webhook_dispatcher(app)
        # W4-CHAN-02A：注册企微自建应用回调 adapter（无配置则跳过）
        _register_wecom_adapter(app)
        # W4-CHAN-02A：启动企微消费循环（收→Agent→发，失败不阻断启动）
        _start_wecom_consumer(app)
        log.info("Harness API server startup complete")
        yield
        # ===== shutdown =====
        _stop_wecom_consumer(app)
        _stop_webhook_dispatcher(app)
        await _close_db()
        log.info("Harness API server shutdown complete")

    app = FastAPI(
        title="Harness API",
        version="0.1.0",
        description="Harness Agent Runtime — Production API",
        lifespan=lifespan,
    )

    # ========== CORS ==========
    try:
        from fastapi.middleware.cors import CORSMiddleware
        from harness.common.config.settings import Settings
        settings = Settings()
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    except Exception:  # noqa: BLE001
        pass

    # ========== 请求上下文（request_id + 指标 + 访问日志） ==========
    from harness.platform.api.middleware import RequestContextMiddleware

    app.add_middleware(RequestContextMiddleware)

    # ========== 统一异常处理 ==========
    from harness.platform.api.exceptions import register_exception_handlers
    register_exception_handlers(app)

    # ========== Prometheus 抓取端点（不走 /api/v1，通常由内网采集） ==========
    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> Response:
        from harness.common.observability.metrics import expose_prometheus

        return Response(
            content=expose_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    # ========== API v1（Controller 层） ==========
    from harness.platform.api.controllers import api_router
    app.include_router(api_router)

    # ========== Gateway WebSocket（渠道接入层） ==========
    from harness.platform.api.controllers.gateway import router as gateway_ws_router
    app.include_router(gateway_ws_router)

    # ========== 前端 SPA 静态托管（web/dist 存在时；W4-CHAN-05） ==========
    # 必须在所有 API 路由之后注册：catch-all 只兜住 API 之外的路径，
    # 让 /login、/oauth/callback 等前端路由由 index.html 接管。
    _mount_frontend_spa(app)

    return app


def _mount_frontend_spa(app: FastAPI) -> None:
    """托管 web/dist 构建产物（SPA history 路由 fallback）。

    - /assets/* 直接回静态文件
    - 文件命中的路径（favicon 等）回文件
    - 其余非 API 路径全部回 index.html，由 vue-router 接管
    - dist 不存在（纯后端部署）时静默跳过
    """
    try:
        from pathlib import Path

        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles

        dist = Path(__file__).resolve().parents[2] / "web" / "dist"
        if not (dist / "index.html").is_file():
            return

        assets_dir = dist / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="spa-assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str) -> Response:
            # API / WS / 指标路径不允许被 SPA 兜底——未命中就是 404
            first = full_path.split("/", 1)[0]
            if first in ("api", "ws", "metrics"):
                from fastapi import HTTPException

                raise HTTPException(status_code=404, detail="Not Found")
            candidate = dist / full_path.lstrip("/")
            # 防目录穿越：resolve 后必须仍在 dist 内
            if full_path and candidate.is_file() and candidate.resolve().is_relative_to(dist):
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    except Exception:  # noqa: BLE001 — 静态托管失败不阻断 API 启动
        pass


# ---------------------------------------------------------------------------
# 启动 / 关闭辅助
# ---------------------------------------------------------------------------


def _init_observability() -> None:
    """启动时初始化 logging + OTel。失败时 graceful skip。"""
    try:
        from harness.common.observability.logging import init_logging
        init_logging()
    except Exception:  # noqa: BLE001
        pass

    try:
        from harness.common.observability import init_otel
        init_otel(service_name="harness")
    except Exception:  # noqa: BLE001
        pass


async def _init_db() -> None:
    """首次启动时 init_db（按实体建表）。

    正式环境以 sql/ 下的留痕脚本为准，这里只兜底开发/测试环境。失败只打 warn。
    """
    try:
        from harness.platform.infra.engine import init_db as _init
        await _init()
        log.info("db.engine: 初始化完成")
    except Exception as exc:  # noqa: BLE001
        log.warning("db.engine: 初始化失败（开发环境可忽略）: %s", exc)


async def _recover_interrupted() -> None:
    """启动恢复：running 运行 / running 计划 → interrupted，streaming 消息 → failed。"""
    try:
        from harness.platform.service.recovery_service import recover_interrupted

        await recover_interrupted()
    except Exception as exc:  # noqa: BLE001 — 恢复失败不阻断启动
        log.warning("recovery: 启动恢复异常（可忽略）: %s", exc)


async def _close_db() -> None:
    """关闭数据库引擎。"""
    try:
        from harness.platform.infra.engine import close_db
        await close_db()
    except Exception:  # noqa: BLE001
        pass


def _start_webhook_dispatcher(app: FastAPI) -> None:
    """启动 Webhook 调度器并挂到 app.state（W4-CHAN-03）。"""
    try:
        from harness.integrations.gateway.webhook_dispatcher import WebhookDispatcher

        dispatcher = WebhookDispatcher()
        dispatcher.start()
        app.state.webhook_dispatcher = dispatcher
        log.info("webhook dispatcher: 已启动并订阅 EventBus")
    except Exception as exc:  # noqa: BLE001 — 不阻断启动
        log.warning("webhook dispatcher 启动失败（可忽略）: %s", exc)


def _stop_webhook_dispatcher(app: FastAPI) -> None:
    """停掉 lifespan 里启动的 Webhook 调度器。"""
    dispatcher = getattr(app.state, "webhook_dispatcher", None)
    if dispatcher is not None:
        try:
            dispatcher.stop()
        except Exception:  # noqa: BLE001
            pass


def _register_wecom_adapter(app: FastAPI) -> None:
    """读取企微配置并挂到 app.state.wecom_adapter（W4-CHAN-02A）。"""
    try:
        from harness.integrations.gateway.adapters.wecom import WeComAdapter
        from harness.integrations.gateway.wecom_config import load_wecom_config

        cfg = load_wecom_config()
        if not cfg:
            log.info("wecom: 未配置，跳过注册")
            return
        adapter = WeComAdapter(cfg)
        app.state.wecom_adapter = adapter
        log.info(
            "wecom: 已注册（corp_id=%s, receive=%s, send=%s）",
            cfg.get("corp_id", "?"),
            adapter.ready_for_receive,
            adapter.ready_for_send,
        )
    except Exception as exc:  # noqa: BLE001 — 不阻断启动
        log.warning("wecom adapter 注册失败（可忽略）: %s", exc)


def _start_wecom_consumer(app: FastAPI) -> None:
    """启动企微消费循环（收→Agent→发；失败不阻断启动）。"""
    try:
        from harness.integrations.gateway.wecom_consumer import start_wecom_consumer

        start_wecom_consumer(app)
    except Exception as exc:  # noqa: BLE001 — 不阻断启动
        log.warning("wecom 消费循环启动失败（可忽略）: %s", exc)


def _stop_wecom_consumer(app: FastAPI) -> None:
    """停掉企微消费循环任务。"""
    try:
        from harness.integrations.gateway.wecom_consumer import stop_wecom_consumer

        stop_wecom_consumer(app)
    except Exception:  # noqa: BLE001
        pass
