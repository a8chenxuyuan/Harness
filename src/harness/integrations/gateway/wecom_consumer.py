"""企微消息消费循环（W4-CHAN-02A 收→Agent→发全链路）。

app lifespan 里启动一个后台任务：
    adapter.receive() → GatewayRouter.dispatch → agent_runner → adapter.send()

agent_runner（联调版，CHAN-05 会换成 channel_bindings 路由）：
    - 固定租户 DEFAULT_TENANT_ID 下自动建/复用 ``wecom_bot`` 用户
      作为 Agent 执行身份；
    - 调 AgentService.run(goal=消息内容, mode="single")；
    - 把 result["output"] 发回企微。
"""

from __future__ import annotations

import asyncio
import logging
import uuid

log = logging.getLogger(__name__)

WECOM_BOT_USERNAME = "wecom_bot"


async def _resolve_agent_user(session) -> tuple[str, str]:
    """查/建 wecom_bot 用户，返回 (user_id, tenant_id)。

    用户不存在时现场创建（member 角色、随机不可登录密码）。
    """
    from harness.platform.entity.user import User
    from harness.platform.repository.user_repository import UserRepository
    from harness.platform.service.auth_service import DEFAULT_TENANT_ID

    repo = UserRepository(session)
    existing = await repo.get_by_username(DEFAULT_TENANT_ID, WECOM_BOT_USERNAME)
    if existing is not None:
        return existing.id, existing.tenant_id

    user = User(
        id=str(uuid.uuid4()),
        tenant_id=DEFAULT_TENANT_ID,
        username=WECOM_BOT_USERNAME,
        email=f"{WECOM_BOT_USERNAME}@channel.local",
        # 不可登录的占位哈希（任意非空即可；正常登录走不到这条路）
        hashed_password=f"channel-bot-{uuid.uuid4().hex}",
        role="member",
    )
    saved = await repo.save(user)
    log.info("wecom: 已创建 Agent 执行用户 %s (%s)", WECOM_BOT_USERNAME, saved.id)
    return saved.id, saved.tenant_id


def make_wecom_agent_runner():
    """构造 agent_runner：RawMessage → AgentService.run → 回复文本。"""

    async def runner(raw) -> str:
        from harness.platform.api.vo.auth_vo import UserInfo
        from harness.platform.infra.engine import get_session_factory
        from harness.platform.service.agent_service import AgentService

        factory = get_session_factory()
        async with factory() as session:
            user_id, tenant_id = await _resolve_agent_user(session)
            user = UserInfo(user_id=user_id, tenant_id=tenant_id, role="member")
            result = await AgentService(user, session).run(
                goal=raw.content or "（空消息）",
                mode="single",
            )
        output = result.get("output")
        if not output:
            return f"Agent 运行结束（{result.get('status')}），但没有返回内容。"
        return str(output)

    return runner


def start_wecom_consumer(app) -> asyncio.Task | None:
    """启动消费循环；adapter 未注册时返回 None。"""
    adapter = getattr(app.state, "wecom_adapter", None)
    if adapter is None:
        return None

    from harness.integrations.gateway.router import GatewayRouter

    router = GatewayRouter()
    router.register(adapter)
    task = asyncio.create_task(
        router.run_all(make_wecom_agent_runner()),
        name="wecom-consumer",
    )
    app.state.wecom_consumer_task = task
    log.info("wecom: 消费循环已启动（收→Agent→发）")
    return task


def stop_wecom_consumer(app) -> None:
    """取消消费循环任务（shutdown 时调用）。"""
    task = getattr(app.state, "wecom_consumer_task", None)
    if task is not None:
        task.cancel()
        app.state.wecom_consumer_task = None


__all__ = ["make_wecom_agent_runner", "start_wecom_consumer", "stop_wecom_consumer"]
