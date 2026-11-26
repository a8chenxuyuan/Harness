"""幂等键 Controller 辅助（W3-KERN-02）。

把 Header 解析、错误映射集中在这里，避免 agents / agent_stream 两个
Controller 各写一份 409 文案。
"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from harness.platform.api.exceptions import BizError
from harness.platform.service.idempotency_service import MAX_KEY_LENGTH, ClaimResult


def normalize_key(raw: str | None) -> str | None:
    """清洗 Idempotency-Key：空串视为未传，超长直接 400。"""
    key = (raw or "").strip()
    if not key:
        return None
    if len(key) > MAX_KEY_LENGTH:
        raise BizError(400, f"Idempotency-Key 长度不能超过 {MAX_KEY_LENGTH}")
    return key


def conflict_error(result: ClaimResult) -> BizError:
    """同步接口的 409：detail 带上 run_id，便于前端跳转。"""
    detail = f"run_id={result.run_id}" if result.run_id else None
    if result.conflict == "hash_mismatch":
        return BizError(409, "幂等键已用于不同的请求体", detail=detail)
    return BizError(409, "相同幂等键的请求正在处理中", detail=detail)


def conflict_response(result: ClaimResult) -> JSONResponse:
    """流式接口的 409：返回 JSON（不建立 SSE），data 里带 run_id。"""
    message = (
        "幂等键已用于不同的请求体"
        if result.conflict == "hash_mismatch"
        else "相同幂等键的请求已存在，请查询运行状态"
    )
    return JSONResponse(
        status_code=409,
        content={
            "code": 409,
            "message": message,
            "detail": None,
            "data": {"run_id": result.run_id},
        },
    )


__all__ = ["conflict_error", "conflict_response", "normalize_key"]
