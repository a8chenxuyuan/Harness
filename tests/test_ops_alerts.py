"""告警规则与 Runbook 校验（W3-OBS-02）。"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ALERTS = ROOT / "ops" / "prometheus" / "alerts.yml"
RUNBOOK = ROOT / "ops" / "runbook.md"

EXPECTED = {
    "HarnessHighErrorRate",
    "HarnessHighLatencyP95",
    "HarnessRateLimitBurst",
    "HarnessModelRetryStorm",
    "HarnessModelCircuitOpen",
    "HarnessTTFTSlow",
    "HarnessSandboxViolation",
    "HarnessServiceDown",
}


def _rules() -> list[dict]:
    data = yaml.safe_load(ALERTS.read_text(encoding="utf-8"))
    groups = data["groups"]
    assert groups, "alerts.yml 至少需要一个 group"
    return [rule for group in groups for rule in group["rules"]]


def test_alert_rules_are_well_formed() -> None:
    """每条规则必须有 alert / expr / for / severity / runbook。"""
    rules = _rules()
    names = [rule["alert"] for rule in rules]
    assert len(names) == len(set(names)), "告警名称不能重复"
    assert set(names) == EXPECTED

    for rule in rules:
        assert rule.get("expr"), rule["alert"]
        assert rule.get("for"), rule["alert"]
        assert rule.get("labels", {}).get("severity") in {"warning", "critical"}
        assert rule.get("annotations", {}).get("runbook"), rule["alert"]


def test_runbook_has_matching_sections() -> None:
    """每条告警的 runbook 锚点都能在 runbook.md 找到对应标题。"""
    text = RUNBOOK.read_text(encoding="utf-8")
    headings = {
        line.lstrip("#").strip().lower()
        for line in text.splitlines()
        if line.startswith("## ")
    }

    for rule in _rules():
        anchor = rule["annotations"]["runbook"].split("#", 1)[-1]
        assert anchor in headings, f"{rule['alert']} 缺少 runbook 章节 #{anchor}"
