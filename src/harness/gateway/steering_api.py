"""中途插话（steering）API（Phase 12 - steering_api）。

客户端可以在 Agent 运行中 POST /api/steer 来：
  - interrupt：立刻打断当前会话，保留状态等用户重新输入
  - continue：在 interrupt 之后恢复运行
  - inject：往当前会话追加一条新的用户消息

本层不实现具体 session 存储——只把调用转发给 ``harness.loop.interrupt``
和上层的 session manager。找不到 session 时返回 None，server 层会转成 404。
"""

from __future__ import annotations

import logging
from typing import Any, Literal

log = logging.getLogger(__name__)

try:
    from pydantic import BaseModel, Field
    _PYDANTIC_OK = True
except ImportError:  # pragma: no cover - 没装 pydantic 时需要单独处理
    _PYDANTIC_OK = False


if _PYDANTIC_OK:

    class SteerRequest(BaseModel):
        """steer 请求体。"""

        session_id: str = Field(..., description="目标会话 id")
        message: str = Field("", description="注入的新消息（inject 时必填）")
        kind: Literal["interrupt", "continue", "inject"] = Field(
            ..., description="操作类型"
        )

        model_config = {"extra": "forbid"}

    class SteerResponse(BaseModel):
        """steer 响应体（成功时）。"""

        ok: bool = True
        session_id: str
        action: Literal["interrupt", "continue", "inject"]


else:  # pragma: no cover - pydantic 未安装时的占位

    class SteerRequest:
        """pydantic 未装时的纯 dict 薄包装。"""

        def __init__(self, session_id: str, message: str = "", kind: str = "") -> None:
            self.session_id = session_id
            self.message = message
            self.kind = kind

        @classmethod
        def model_validate(cls, body: dict[str, Any]) -> "SteerRequest":
            return cls(**body)

    class SteerResponse:
        def __init__(self, ok: bool, session_id: str, action: str) -> None:
            self.ok = ok
            self.session_id = session_id
            self.action = action


# ---------------------------------------------------------------------------
# steer 函数
# ---------------------------------------------------------------------------

# 进程内 session → AgentState 的注册表（server 启动时可以注入）
_SESSION_REGISTRY: dict[str, Any] = {}


def register_session(session_id: str, state: Any) -> None:
    """注册一个活动 session。

    Args:
        session_id: 会话 id。
        state: AgentState 实例。
    """
    _SESSION_REGISTRY[session_id] = state


def unregister_session(session_id: str) -> None:
    """注销一个 session。"""
    _SESSION_REGISTRY.pop(session_id, None)


async def steer(req: SteerRequest) -> dict[str, Any] | None:
    """执行 steer 请求。

    Args:
        req: SteerRequest。

    Returns:
        成功时返回 {"session_id": ..., "action": ...}；找不到 session 时返回 None。
    """
    state = _SESSION_REGISTRY.get(req.session_id)
    if state is None:
        log.warning("steer: session %s 不存在", req.session_id)
        return None

    kind = req.kind
    if kind == "interrupt":
        from harness.loop.interrupt import interrupt
        interrupt(state, reason="user_steer_interrupt")
        log.info("steer interrupt session=%s", req.session_id)
        return {"session_id": req.session_id, "action": "interrupt"}

    if kind == "continue":
        from harness.loop.interrupt import resume
        resume(state)
        log.info("steer continue session=%s", req.session_id)
        return {"session_id": req.session_id, "action": "continue"}

    if kind == "inject":
        if not req.message:
            return {"error": "inject requires non-empty message"}
        # 往 state.messages 里追加一条 user message
        try:
            from harness.message.helpers import user_message
            state.messages.append(user_message(text=req.message))
            log.info("steer inject session=%s msg=%s", req.session_id, req.message[:50])
        except Exception as exc:  # noqa: BLE001
            log.exception("steer inject 失败")
            return {"error": f"inject failed: {exc}"}
        return {"session_id": req.session_id, "action": "inject"}

    return {"error": f"unknown steer kind: {kind}"}
