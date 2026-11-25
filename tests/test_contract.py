"""OpenAPI 契约测试。

接口 schema 是前后端与渠道方的契约，任何变更必须显式更新快照：

    $env:PYTHONPATH="src"; $env:UPDATE_OPENAPI_SNAPSHOT="1"; pytest tests/test_contract.py

平时只做比对，缺失或变更即失败，避免接口被无意修改。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SNAPSHOT_PATH = Path(__file__).with_name("openapi_snapshot.json")


def test_openapi_matches_snapshot(app) -> None:
    """当前 app 的 OpenAPI schema 必须与快照一致。"""
    current = json.loads(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True)
    )

    if os.environ.get("UPDATE_OPENAPI_SNAPSHOT") == "1":
        SNAPSHOT_PATH.write_text(
            json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return

    assert SNAPSHOT_PATH.exists(), (
        f"缺少 OpenAPI 快照 {SNAPSHOT_PATH}，"
        "请用 UPDATE_OPENAPI_SNAPSHOT=1 生成后提交"
    )
    saved = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

    added = sorted(set(current["paths"]) - set(saved["paths"]))
    removed = sorted(set(saved["paths"]) - set(current["paths"]))
    assert current == saved, (
        "OpenAPI 契约发生变化，请确认后用 UPDATE_OPENAPI_SNAPSHOT=1 重新生成快照。"
        f"新增路径={added} 删除路径={removed}"
    )
