"""Agent 接口：运行 / 计划 / 后台执行 / 状态 / 取消（Phase 23）。

薄 Controller：参数校验 + 调 Service + 统一响应；
Plan 执行走 ``service.run_registry`` 的后台 asyncio.Task，
本进程重启会丢失运行态（持久化运行队列不在 Phase 23 范围）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from harness.platform.api.deps import get_current_user, get_db
from harness.platform.api.dto.agent_dto import AgentRunRequest
from harness.platform.api.vo.agent_vo import AgentRunResponse
from harness.platform.api.vo.auth_vo import UserInfo
from harness.platform.api.vo.envelope_vo import ApiResponse
from harness.platform.api.dto.plan_dto import AgentPlanRequest
from harness.platform.api.vo.plan_vo import (
    AgentCancelResponse,
    AgentExecuteResponse,
    AgentPlanResponse,
    AgentStatusResponse,
    PlanSummary,
)
from harness.platform.service.rate_limit import run_rate_limit

router = APIRouter(prefix="/agents", tags=["agents"])
log = logging.getLogger(__name__)


@router.post("/run", response_model=ApiResponse[AgentRunResponse])
async def run_agent(
    req: AgentRunRequest,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description="幂等键（可选）"
    ),
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _rate: None = Depends(run_rate_limit),
) -> dict:
    """同步运行 Agent。

    mode=single 直接跑单 Agent；
    mode=coordinator 走 Plan → Review → Executor 完整多 Agent 链路。
    传 ``Idempotency-Key`` 时：同 key + 同请求体重复调用直接回放上次结果。
    """
    from harness.platform.api.exceptions import BizError
    from harness.platform.api.idempotency_helpers import conflict_error, normalize_key
    from harness.platform.auth.audit import record_audit
    from harness.platform.service.agent_service import AgentService
    from harness.platform.service.idempotency_service import (
        SCOPE_RUN,
        IdempotencyService,
        hash_request,
    )

    key = normalize_key(idempotency_key)
    idem = IdempotencyService(db)
    record = None
    if key is not None:
        claim = await idem.claim(
            user.tenant_id,
            SCOPE_RUN,
            key,
            hash_request(req.model_dump()),
            replay_completed=True,
        )
        if claim.cached is not None:
            return {"code": 0, "message": "ok", "data": claim.cached}
        if claim.conflict:
            raise conflict_error(claim)
        record = claim.record

    try:
        result = await AgentService(user, db).run(
            goal=req.goal,
            mode=req.mode,
            conversation_id=req.conversation_id,
        )
    except BizError:
        if record is not None:
            await idem.release(record)
        raise
    except Exception as exc:  # noqa: BLE001
        if record is not None:
            await idem.release(record)
        await record_audit(
            db,
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            action="agent.run",
            target=req.mode,
            result="error",
            session_id=req.conversation_id,
            detail={"error": str(exc)},
        )
        raise

    if record is not None:
        try:
            await idem.complete(record, result)
        except Exception as exc:  # noqa: BLE001 — 缓存写入失败不影响本次结果
            log.warning("idempotency: 缓存写入失败 key=%s err=%s", key, exc)

    await record_audit(
        db,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        action="agent.run",
        target=req.mode,
        result=result.get("status", "success"),
        session_id=req.conversation_id,
        detail={"run_id": result.get("run_id"), "goal": req.goal[:200]},
    )
    return {"code": 0, "message": "ok", "data": result}


@router.post("/plan", response_model=ApiResponse[AgentPlanResponse])
async def create_plan(
    req: AgentPlanRequest,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """用显式 steps 创建 Plan 并落库（approved=False，等待审批）。"""
    from harness.platform.auth.audit import record_audit
    from harness.platform.repository.plan_repository import PlanRepository
    from harness.platform.service.plan_service import PlanService

    service = PlanService(db, user)
    record = await service.create_plan(
        req.goal, [step.model_dump() for step in req.steps]
    )
    await record_audit(
        db,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        action="plan.create",
        target=record.plan_id,
        detail={"goal": req.goal[:200]},
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {"plan": PlanSummary(**PlanRepository.to_dict(record))},
    }


@router.post(
    "/{agent_id}/execute",
    response_model=ApiResponse[AgentExecuteResponse],
    status_code=202,
)
async def execute_plan(
    agent_id: str,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """审批并后台执行指定 Plan（agent_id 即 plan_id）。

    执行在后台 asyncio.Task 中进行，立即返回 202；进度用 status 接口轮询。
    """
    from harness.platform.auth.audit import record_audit
    from harness.platform.service.plan_service import PlanService

    service = PlanService(db, user)
    record = await service.get(agent_id)
    if not record.approved:
        record.approved = True
        await service.repo.save(record)
    await service.repo.update_status(record, "running")

    _spawn_execution(agent_id, user.tenant_id, user.user_id)
    await record_audit(
        db,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        action="plan.execute",
        target=agent_id,
    )
    return {
        "code": 0,
        "message": "accepted",
        "data": {"plan_id": agent_id, "run_id": agent_id, "status": "running"},
    }


@router.get("/{agent_id}/status", response_model=ApiResponse[AgentStatusResponse])
async def get_plan_status(
    agent_id: str,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询后台运行状态；注册表无记录时回落到 plans 表状态。"""
    from harness.platform.service.plan_service import PlanService
    from harness.platform.service.run_registry import get_run_registry

    snapshot = get_run_registry().status(agent_id)
    if snapshot is not None:
        return {"code": 0, "message": "ok", "data": snapshot}

    record = await PlanService(db, user).get(agent_id)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "run_id": agent_id,
            "status": record.status,
            "output": None,
            "error": None,
        },
    }


@router.post("/{agent_id}/cancel", response_model=ApiResponse[AgentCancelResponse])
async def cancel_plan(
    agent_id: str,
    user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """请求取消后台运行；已结束或不存在时回落到 plans 表状态。"""
    from harness.platform.auth.audit import record_audit
    from harness.platform.service.plan_service import PlanService
    from harness.platform.service.run_registry import get_run_registry

    service = PlanService(db, user)
    cancelled = get_run_registry().cancel(agent_id)
    record = await service.get(agent_id)
    if cancelled and record.status not in ("done", "failed", "cancelled"):
        await service.repo.update_status(record, "cancelled")

    await record_audit(
        db,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        action="plan.cancel",
        target=agent_id,
        result="success" if cancelled else "noop",
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {"run_id": agent_id, "status": "cancelled" if cancelled else record.status},
    }


# ---------------------------------------------------------------------------
# 内部：后台执行
# ---------------------------------------------------------------------------


def _spawn_execution(plan_id: str, tenant_id: str, user_id: str) -> None:
    """启动后台执行（独立 DB session，不占用请求 session）。"""
    from harness.platform.service.run_registry import get_run_registry

    async def _job() -> str:
        from harness.platform.api.vo.auth_vo import UserInfo
        from harness.platform.infra.engine import get_session_factory
        from harness.platform.repository.plan_repository import PlanRepository
        from harness.platform.service.plan_service import PlanService

        factory = get_session_factory()
        async with factory() as session:
            record = await PlanRepository(session).get_by_id(tenant_id, plan_id)
            if record is None:
                raise RuntimeError(f"plan {plan_id} 已删除，执行中止")
            user = UserInfo(user_id=user_id, tenant_id=tenant_id, role="member")
            return await PlanService(session, user).execute(record)

    get_run_registry().start(plan_id, _job())


__all__ = ["router"]
