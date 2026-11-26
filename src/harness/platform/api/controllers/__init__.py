"""API Controller 层组装点。

本目录对应 Java 项目的 Controller 层：每个文件一组同域路由，
只做参数解析、鉴权与调用 service，不写业务逻辑。

把各 Controller 的 router 统一 include 到 ``api_router``，
再由 app.py 挂载到 FastAPI 实例上。URL 前缀保持 ``/api/v1``（接口版本）。
"""

from __future__ import annotations

from fastapi import APIRouter

from .agent_stream import router as agent_stream_router
from .agents import router as agents_router
from .apikeys import router as api_keys_router
from .auth import router as auth_router
from .channels import router as channels_router
from .health import router as health_router
from .hitl import router as hitl_router
from .memories import router as memories_router
from .messages import router as messages_router
from .mcp import router as mcp_router
from .observability import router as observability_router
from .plans import router as plans_router
from .runs import router as runs_router
from .sessions import router as sessions_router
from .skills import router as skills_router
from .steer import router as steer_router
from .tenant import router as tenant_router
from .tools import router as tools_router

api_router = APIRouter(prefix="/api/v1", tags=["v1"])
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(api_keys_router)
api_router.include_router(agent_stream_router)
api_router.include_router(agents_router)
api_router.include_router(plans_router)
api_router.include_router(sessions_router)
api_router.include_router(messages_router)
api_router.include_router(runs_router)
api_router.include_router(steer_router)
api_router.include_router(hitl_router)
api_router.include_router(memories_router)
api_router.include_router(skills_router)
api_router.include_router(tools_router)
api_router.include_router(mcp_router)
api_router.include_router(observability_router)
api_router.include_router(channels_router)
api_router.include_router(tenant_router)

__all__ = ["api_router"]
