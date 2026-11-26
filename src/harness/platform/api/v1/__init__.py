"""API v1 版本组装点。

把各 Controller 的 router 统一 include 到 ``api_v1``，
再由 app.py 挂载到 FastAPI 实例上。
"""

from __future__ import annotations

from fastapi import APIRouter

from .agent_stream import router as agent_stream_router
from .agents import router as agents_router
from .auth import router as auth_router
from .channels import router as channels_router
from .health import router as health_router
from .hitl import router as hitl_router
from .messages import router as messages_router
from .observability import router as observability_router
from .plans import router as plans_router
from .runs import router as runs_router
from .sessions import router as sessions_router
from .steer import router as steer_router
from .tools import router as tools_router

api_v1 = APIRouter(prefix="/api/v1", tags=["v1"])
api_v1.include_router(health_router)
api_v1.include_router(auth_router)
api_v1.include_router(agent_stream_router)
api_v1.include_router(agents_router)
api_v1.include_router(plans_router)
api_v1.include_router(sessions_router)
api_v1.include_router(messages_router)
api_v1.include_router(runs_router)
api_v1.include_router(steer_router)
api_v1.include_router(hitl_router)
api_v1.include_router(tools_router)
api_v1.include_router(observability_router)
api_v1.include_router(channels_router)

__all__ = ["api_v1"]
