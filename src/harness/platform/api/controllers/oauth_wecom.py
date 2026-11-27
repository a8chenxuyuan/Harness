"""企微 OAuth 登录接口（W4-CHAN-05）。

接口清单：
    GET /auth/wecom/login     发起授权（302 → 企微扫码页）
    GET /auth/wecom/callback  授权回调（code 换 userid → 建/查绑定 →
                              签发双 token → 302 回前端 /oauth/callback）

不走 /api/v1 前缀之外的鉴权（本身是免密登录入口）。
前端回跳地址由 request.base_url 推导（隧道场景依赖代理头），
env ``HARNESS_PUBLIC_BASE_URL`` 可显式覆盖。
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from harness.platform.service import wecom_oauth_service as svc

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/wecom", tags=["oauth-wecom"])


def _public_base_url(request: Request) -> str:
    """前端可访问的站点根地址（带尾斜杠）。"""
    override = os.environ.get("HARNESS_PUBLIC_BASE_URL")
    if override:
        return override.rstrip("/") + "/"
    return str(request.base_url)


def _get_adapter(request: Request):
    """取 WeComAdapter；缺失时返回 None（login 返回 503）。"""
    return getattr(request.app.state, "wecom_adapter", None)


@router.get("/login")
async def wecom_login(request: Request, redirect: str = "/"):
    """发起企微授权登录。

    Query:
        redirect: 登录成功后前端回跳路径（默认 /）。
    """
    adapter = _get_adapter(request)
    cfg = getattr(adapter, "config", None) or {}
    corp_id = cfg.get("corp_id")
    agent_id = cfg.get("agent_id")
    if not corp_id or not agent_id:
        return RedirectResponse(
            url="/login?error=" + urlencode({"error": "企微登录未配置"}),
            status_code=302,
        )

    state = svc.create_login_state(redirect)
    callback_uri = _public_base_url(request).rstrip("/") + "/api/v1/auth/wecom/callback"
    login_url = svc.build_login_url(corp_id, agent_id, callback_uri, state)
    return RedirectResponse(url=login_url, status_code=302)


@router.get("/callback")
async def wecom_callback(request: Request, code: str = "", state: str = ""):
    """企微授权回调：code 换 userid → 绑定/登录 → 302 回前端。"""
    frontend = _public_base_url(request).rstrip("/")

    redirect_path = svc.consume_login_state(state) if state else None
    if redirect_path is None:
        return RedirectResponse(
            url=f"{frontend}/oauth/callback?error=state 无效或已过期",
            status_code=302,
        )

    adapter = _get_adapter(request)
    if adapter is None:
        return RedirectResponse(
            url=f"{frontend}/oauth/callback?error=企微登录未配置",
            status_code=302,
        )

    try:
        from harness.platform.infra.engine import get_session_factory
        from harness.platform.service.wecom_oauth_service import (
            exchange_code,
            wecom_login_or_bind,
        )

        userid = await exchange_code(adapter, code)
        factory = get_session_factory()
        async with factory() as session:
            tokens = await wecom_login_or_bind(session, userid)
    except Exception as exc:  # noqa: BLE001 — 统一回前端错误页
        log.warning("wecom OAuth callback 失败: %s", exc)
        return RedirectResponse(
            url=f"{frontend}/oauth/callback?error=" + urlencode({"error": str(exc)}),
            status_code=302,
        )

    # 成功固定回前端落地页 /oauth/callback；state 里的 redirect 作为参数
    # 传递，由落地页读 token 后再跳转
    params = {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "redirect": redirect_path if redirect_path.startswith("/") else "/",
    }
    return RedirectResponse(
        url=f"{frontend}/oauth/callback?{urlencode(params)}",
        status_code=302,
    )


__all__ = ["router"]
