"""健康检查 & 指标接口。

/metrics 默认输出 Prometheus 文本格式（抓取端友好），
``?format=json`` 保留原有 dict 快照，兼容既有调试脚本。
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from harness.platform.api.dto.common import ApiResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiResponse[dict[str, Any]])
async def health() -> dict[str, Any]:
    """服务存活检查。"""
    return {
        "code": 0,
        "message": "ok",
        "data": {"status": "ok", "version": "0.1.0"},
    }


@router.get("/metrics")
async def metrics(format: str = Query(default="prometheus", pattern="^(prometheus|json)$")):
    """暴露进程指标。

    Args:
        format: ``prometheus``（默认，文本）或 ``json``（dict 快照）。
    """
    try:
        from harness.common.observability import expose_dict

        data = expose_dict()
    except Exception:  # noqa: BLE001
        data = {}

    if format == "json":
        return {"code": 0, "message": "ok", "data": data}
    return PlainTextResponse(
        _to_prometheus(data), media_type="text/plain; version=0.0.4; charset=utf-8"
    )


def _to_prometheus(data: dict[str, Any]) -> str:
    """把 dict 快照转成 Prometheus 文本格式（无直方图分桶，只导出标量）。"""
    lines: list[str] = []
    for key, value in data.items():
        metric = re.sub(r"[^a-zA-Z0-9_]", "_", key)
        if isinstance(value, dict):
            for label, val in value.items():
                if isinstance(val, (int, float)):
                    safe = str(label).replace("\\", "\\\\").replace('"', '\\"')
                    lines.append(f'{metric}{{label="{safe}"}} {val}')
        elif isinstance(value, (int, float)):
            lines.append(f"{metric} {value}")
    return "\n".join(lines) + ("\n" if lines else "")
