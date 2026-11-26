"""WebSocket /ws/chat（原 gateway/server.py 里的 WebSocket 端点）。

注意：这个 router 不走 /api/v1 前缀，直接挂根路径。
Gateway 渠道接入层的核心路由入口。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from harness.platform.api.deps import get_gateway_router

log = logging.getLogger(__name__)

router = APIRouter(tags=["gateway"])


@router.websocket("/ws/chat")
async def ws_chat(
    ws: WebSocket,
    gateway_router=Depends(get_gateway_router),
) -> None:
    """WebChat 渠道 WebSocket 端点。"""
    from harness.integrations.gateway.adapters.webchat import WebChatAdapter, parse_ws_message

    await ws.accept()

    # 找 WebChatAdapter
    webchat = gateway_router.adapters.get("webchat")
    if webchat is None or not isinstance(webchat, WebChatAdapter):
        try:
            await ws.send_text("channel webchat 未注册")
        except Exception:  # noqa: BLE001
            pass
        await ws.close()
        return

    user_id = (
        ws.query_params.get("user_id")
        or f"{ws.client.host}:{ws.client.port}"
    )
    webchat.bind_ws(user_id, ws)
    log.info("ws/chat connected user=%s", user_id)

    # Agent runner 从 WebSocket 的 app.state 取（GatewayServer.start() 时注入）
    app_state = ws.app.state if hasattr(ws, "app") else None
    agent_runner = getattr(app_state, "agent_runner", None) if app_state else None

    try:
        while True:
            raw_text = await ws.receive_text()
            raw = await parse_ws_message(raw_text, user_id)
            if agent_runner is None:
                await ws.send_text("agent_runner not configured")
                continue
            result = await gateway_router.dispatch(raw, agent_runner)
            if not result.ok:
                log.warning("ws/chat dispatch failed: %s", result.error)
    except WebSocketDisconnect:
        log.info("ws/chat disconnected user=%s", user_id)
    except Exception:  # noqa: BLE001
        log.exception("ws/chat 异常")
    finally:
        webchat.unbind_ws(user_id)
