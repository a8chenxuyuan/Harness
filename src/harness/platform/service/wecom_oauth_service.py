"""企微 OAuth 网页授权服务（W4-CHAN-05）。

流程（企业微信授权登录组件，浏览器扫码）：
    1. GET /api/v1/auth/wecom/login
       → 302 到企微登录页：
         https://login.work.weixin.qq.com/wwlogin/sso/login
           ?login_type=CorpApp&appid={corp_id}&agentid={agent_id}
           &redirect_uri={callback}&state={state}
    2. 用户扫码授权 → 企微回调 GET /api/v1/auth/wecom/callback?code&state
    3. 校验 state（一次性，10 分钟）→ 用 code 换 userid：
       GET /cgi-bin/auth/getuserinfo?access_token=..&code=..
    4. 按 (wecom, userid) 查绑定：命中直接登录；未命中自动建账号+绑定
    5. 302 回前端 /oauth/callback?access_token=..&refresh_token=..

state 存进程内存（单实例足够；多实例部署换 Redis）。
"""

from __future__ import annotations

import logging
import time
import urllib.parse
import uuid

from harness.platform.api.exceptions import BizError
from harness.platform.auth.oauth_crypto import new_state_token

log = logging.getLogger(__name__)

# state -> (redirect_path, expire_at)；10 分钟过期
_STATES: dict[str, tuple[str, float]] = {}
STATE_TTL_SECONDS = 600

WWLOGIN_URL = "https://login.work.weixin.qq.com/wwlogin/sso/login"
GETUSERINFO_URL = "https://qyapi.weixin.qq.com/cgi-bin/auth/getuserinfo"


# ---------------------------------------------------------------------------
# state 管理（防 CSRF）
# ---------------------------------------------------------------------------

def create_login_state(redirect: str = "/") -> str:
    """签发一次性 state，返回 state 字符串。"""
    _prune_expired_states()
    state = new_state_token()
    _STATES[state] = (redirect, time.time() + STATE_TTL_SECONDS)
    return state


def consume_login_state(state: str) -> str | None:
    """消费 state：有效返回 redirect，否则 None（一次性）。"""
    record = _STATES.pop(state, None)
    if record is None:
        return None
    redirect, expire_at = record
    if time.time() > expire_at:
        return None
    return redirect


def _prune_expired_states() -> None:
    """清理过期 state，防止内存膨胀。"""
    now = time.time()
    expired = [k for k, (_, exp) in _STATES.items() if now > exp]
    for k in expired:
        _STATES.pop(k, None)


# ---------------------------------------------------------------------------
# 登录地址
# ---------------------------------------------------------------------------

def build_login_url(corp_id: str, agent_id: str, redirect_uri: str, state: str) -> str:
    """拼企微授权登录页地址（redirect_uri 需 percent-encode）。"""
    query = urllib.parse.urlencode(
        {
            "login_type": "CorpApp",
            "appid": corp_id,
            "agentid": agent_id,
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return f"{WWLOGIN_URL}?{query}"


# ---------------------------------------------------------------------------
# code → userid
# ---------------------------------------------------------------------------

async def exchange_code(adapter, code: str) -> str:
    """用网页授权 code 换企微 UserID。

    Args:
        adapter: WeComAdapter（复用其 access_token 缓存与 httpx）。
        code: 企微回调带来的授权码（5 分钟有效，一次性）。

    Returns:
        企微 UserID。

    Raises:
        BizError(401): code 无效 / 已使用 / 企微接口报错。
    """
    import httpx

    access_token = await adapter._get_access_token()
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            GETUSERINFO_URL,
            params={"access_token": access_token, "code": code},
        )
        body = resp.json()
    if resp.status_code != 200 or body.get("errcode") not in (0, None):
        log.warning("wecom getuserinfo 失败: %s %s", resp.status_code, body)
        raise BizError(401, f"企微授权码校验失败（errcode={body.get('errcode')}）")
    userid = body.get("userid") or body.get("UserId")
    if not userid:
        raise BizError(401, "企微未返回 userid（授权范围不足或非应用内用户）")
    return str(userid)


# ---------------------------------------------------------------------------
# 登录 / 建绑定
# ---------------------------------------------------------------------------

async def wecom_login_or_bind(session, userid: str, display_name: str = ""):
    """按绑定登录或自动建账号 + 绑定，返回 LoginResponse。

    - 绑定命中：校验用户仍存在且启用 → 更新 last_login_at → 签发双 token
    - 未命中：建 harness 用户（username=wecom_{userid}，随机不可登录
      密码，member）+ 建绑定 → 签发双 token
    """
    from harness.platform.auth.password import hash_password
    from harness.platform.entity.channel import ChannelBinding
    from harness.platform.entity.user import User
    from harness.platform.repository.channel_binding_repository import (
        ChannelBindingRepository,
    )
    from harness.platform.repository.user_repository import UserRepository
    from harness.platform.service.auth_service import AuthService, DEFAULT_TENANT_ID

    now = _utcnow()
    repo = ChannelBindingRepository(session)
    binding = await repo.get_by_platform_user("wecom", userid)
    users = UserRepository(session)

    if binding is not None:
        user = await users.get(binding.harness_user_id)
        if user is None or not user.is_active:
            raise BizError(401, "绑定的平台账号已不存在或被禁用，请联系管理员")
        binding.last_login_at = now
        if display_name and binding.display_name != display_name:
            binding.display_name = display_name
        await repo.save(binding)
    else:
        username = f"wecom_{userid}"
        existing_user = await users.get_by_username(DEFAULT_TENANT_ID, username)
        user = existing_user or User(
            id=str(uuid.uuid4()),
            tenant_id=DEFAULT_TENANT_ID,
            username=username,
            email=f"{username}@channel.wecom.local",
            # 不可登录的占位哈希；企微用户正常走 OAuth 登录
            hashed_password=hash_password(f"oauth-{uuid.uuid4().hex}"),
            role="member",
            is_active=True,
        )
        if existing_user is None:
            await users.save(user)
        binding = ChannelBinding(
            id=str(uuid.uuid4()),
            platform="wecom",
            platform_user_id=userid,
            harness_user_id=user.id,
            tenant_id=user.tenant_id,
            display_name=display_name,
            status="active",
            last_login_at=now,
        )
        await repo.save(binding)
        log.info("wecom: 新建绑定 %s → user %s", userid, user.id)

    auth = AuthService(session)
    return await auth.issue_tokens_for(user)


def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


__all__ = [
    "build_login_url",
    "consume_login_state",
    "create_login_state",
    "exchange_code",
    "wecom_login_or_bind",
]
