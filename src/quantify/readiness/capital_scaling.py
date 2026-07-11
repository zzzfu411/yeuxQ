"""Capital scaling gate for gradual manual deployment decisions."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quantify.data.cache_metadata import cache_metadata_blockers
from quantify.readiness.gate import approval_snapshot_blockers

ScalingDecision = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class CapitalScalingPlan:
    decision: ScalingDecision
    current_capital: float
    proposed_capital: float
    max_allowed_capital: float
    max_increment: float
    allowed_stage: str
    evidence: list[dict[str, str]]
    blockers: list[str]
    rules: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "current_capital": self.current_capital,
            "proposed_capital": self.proposed_capital,
            "max_allowed_capital": self.max_allowed_capital,
            "max_increment": self.max_increment,
            "allowed_stage": self.allowed_stage,
            "evidence": self.evidence,
            "blockers": self.blockers,
            "rules": self.rules,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Capital Scaling Plan: {self.decision}",
            "",
            f"- Current capital: {self.current_capital:.2f}",
            f"- Proposed capital: {self.proposed_capital:.2f}",
            f"- Max allowed capital: {self.max_allowed_capital:.2f}",
            f"- Max increment: {self.max_increment:.2f}",
            f"- Allowed stage: `{self.allowed_stage}`",
            "",
            "## Evidence",
            "",
            "| evidence | status | artifact |",
            "| --- | --- | --- |",
        ]
        for item in self.evidence:
            lines.append(f"| {item['name']} | `{item['status']}` | `{item['artifact']}` |")
        lines.extend(["", "## Blockers"])
        lines.extend(f"- {item}" for item in self.blockers) if self.blockers else lines.append("- None.")
        lines.extend(["", "## Scaling Rules"])
        lines.extend(f"- {item}" for item in self.rules)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_capital_scaling_plan(
    report_dir: str | Path,
    *,
    current_capital: float,
    proposed_capital: float,
    max_increment_pct: float = 0.25,
    min_paper_days: int = 40,
) -> CapitalScalingPlan:
    root = Path(report_dir)
    evidence = _evidence(root)
    blockers = _blockers(evidence)
    approval = _read_json(root / "approval_record.json")
    blockers.extend(_approval_field_blockers(approval))
    blockers.extend(
        f"{code}: {message}"
        for code, message in approval_snapshot_blockers(root, approval)
    )
    paper_stability = _read_json(root / "paper_stability.json")
    observed_days = int(paper_stability.get("observed_days", 0) or 0)
    if observed_days < min_paper_days:
        blockers.append(
            f"Paper observation has {observed_days} days; at least {min_paper_days} are required before capital increase."
        )
    blockers.extend(_run_manifest_blockers(_read_json(root / "run_manifest.json")))
    max_increment = max(current_capital * max_increment_pct, 0.0)
    max_allowed = current_capital + max_increment if not blockers else current_capital
    if proposed_capital > max_allowed:
        blockers.append(
            f"Proposed capital {proposed_capital:.2f} exceeds max allowed {max_allowed:.2f}."
        )
    decision = "BLOCK" if blockers else "PASS"
    return CapitalScalingPlan(
        decision=decision,
        current_capital=current_capital,
        proposed_capital=proposed_capital,
        max_allowed_capital=max_allowed,
        max_increment=max_increment,
        allowed_stage="manual_reference_only" if decision == "PASS" else "research_or_paper_only",
        evidence=evidence,
        blockers=blockers,
        rules=[
            f"Increase capital by at most {max_increment_pct:.0%} after a fresh full review.",
            "Any BLOCK resets allowed capital to the current capital.",
            "Every capital increase needs a new data audit, robustness report, paper stability review, LLM review, and approval record.",
            "Use manual reference sheets only; no unattended broker order flow.",
        ],
        prohibited_actions=[
            "Do not jump directly to the target capital.",
            "Do not increase capital after demo-only or stale-data evidence.",
            "Do not increase capital while paper stability, readiness, or approval is missing.",
            "Do not use this plan as a guarantee of profit.",
        ],
    )


def write_capital_scaling_plan(plan: CapitalScalingPlan, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "capital_scaling_plan.json").write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "capital_scaling_plan.md").write_text(plan.to_markdown(), encoding="utf-8")
    return root


def _evidence(root: Path) -> list[dict[str, str]]:
    checks = [
        ("capital_goal_status", "capital_goal_status.json", "decision"),
        ("micro_live_readiness", "micro_live_readiness.json", "decision"),
        ("paper_stability", "paper_stability.json", "status"),
        ("approval_record", "approval_record.json", None),
        ("run_manifest", "run_manifest.json", None),
    ]
    evidence = []
    for name, artifact, status_key in checks:
        path = root / artifact
        payload = _read_json(path)
        status = _status(payload, status_key=status_key, exists=path.exists())
        if name == "run_manifest" and payload.get("demo_data_used") is True:
            status = "BLOCK"
        evidence.append({"name": name, "artifact": artifact, "status": status})
    return evidence


def _blockers(evidence: list[dict[str, str]]) -> list[str]:
    return [
        f"{item['name']} is {item['status']} ({item['artifact']})."
        for item in evidence
        if item["status"] != "PASS"
    ]


def _approval_field_blockers(approval: dict[str, Any]) -> list[str]:
    if not approval:
        return []
    if approval.get("approval_required") is not True:
        return ["INVALID_APPROVAL: approval_required must be true before capital scaling."]
    missing = [
        key
        for key in ["approved_by", "approved_at", "approval_notes"]
        if not str(approval.get(key, "")).strip()
    ]
    blockers = [f"INVALID_APPROVAL: missing approval fields: {', '.join(missing)}."] if missing else []
    if approval.get("allowed_stage") != "micro_live_ready":
        blockers.append("INVALID_APPROVAL: allowed_stage must be micro_live_ready before capital scaling.")
    return blockers


def _run_manifest_blockers(manifest: dict[str, Any]) -> list[str]:
    if not manifest:
        return []
    blockers: list[str] = []
    if not str(manifest.get("in_sample_end", "") or "").strip():
        blockers.append("RUN_MANIFEST: missing in_sample_end.")
    if not str(manifest.get("out_sample_start", "") or "").strip():
        blockers.append("RUN_MANIFEST: missing out_sample_start.")
    data_version = manifest.get("data_version", {})
    if not isinstance(data_version, dict):
        blockers.append("RUN_MANIFEST: data_version must be an object with source QA provenance.")
        return blockers
    metadata = dict(data_version)
    metadata["data_source_qa_require_evidence_manifest"] = "true"
    blockers.extend(f"RUN_MANIFEST: {item}" for item in cache_metadata_blockers(metadata))
    return blockers


def _status(payload: dict[str, Any], *, status_key: str | None, exists: bool) -> ScalingDecision:
    if not exists:
        return "BLOCK"
    if status_key is None:
        return "PASS" if payload else "BLOCK"
    value = str(payload.get(status_key, "BLOCK")).upper()
    if value == "PASS":
        return "PASS"
    if value == "WATCH":
        return "WATCH"
    return "BLOCK"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
