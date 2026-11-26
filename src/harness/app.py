"""Harness 应用工厂（对应 Java 的 Application.java）。

职责：
    1. 构造 FastAPI 实例
    2. 挂中间件（CORS）
    3. 挂载 API v1 路由 + Gateway WebSocket
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
        log.info("Harness API server startup complete")
        yield
        # ===== shutdown =====
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

    # ========== API v1 ==========
    from harness.platform.api.v1 import api_v1
    app.include_router(api_v1)

    # ========== Gateway WebSocket（渠道接入层） ==========
    from harness.platform.api.v1.gateway import router as gateway_ws_router
    app.include_router(gateway_ws_router)

    return app


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


async def _close_db() -> None:
    """关闭数据库引擎。"""
    try:
        from harness.platform.infra.engine import close_db
        await close_db()
    except Exception:  # noqa: BLE001
        pass
