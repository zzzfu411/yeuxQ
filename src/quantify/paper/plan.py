"""Plan whether a candidate is allowed to enter continuous paper observation."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quantify.data.cache_metadata import cache_metadata_blockers

PaperPlanDecision = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class PaperCandidatePlan:
    decision: PaperPlanDecision
    candidate: str
    report_dir: str
    paper_state_dir: str
    command: str
    required_evidence: list[dict[str, str]]
    blockers: list[str]
    notes: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "candidate": self.candidate,
            "report_dir": self.report_dir,
            "paper_state_dir": self.paper_state_dir,
            "command": self.command,
            "required_evidence": self.required_evidence,
            "blockers": self.blockers,
            "notes": self.notes,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Paper Candidate Plan: {self.decision}",
            "",
            f"- Candidate: `{self.candidate or 'none'}`",
            f"- Report directory: `{self.report_dir}`",
            f"- Paper state directory: `{self.paper_state_dir}`",
            f"- Command: `{self.command or 'not available'}`",
            "",
            "## Required Evidence",
            "",
            "| evidence | status | artifact |",
            "| --- | --- | --- |",
        ]
        for item in self.required_evidence:
            lines.append(f"| {item['name']} | `{item['status']}` | `{item['artifact']}` |")
        lines.extend(["", "## Blockers"])
        lines.extend(f"- {item}" for item in self.blockers) if self.blockers else lines.append("- None.")
        lines.extend(["", "## Notes"])
        lines.extend(f"- {item}" for item in self.notes)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_paper_candidate_plan(
    report_dir: str | Path,
    *,
    config_path: str | Path,
    paper_state_dir: str | Path,
    candidate: str | None = None,
) -> PaperCandidatePlan:
    root = Path(report_dir)
    selected = candidate or _best_candidate(root)
    evidence = _required_evidence(root, selected)
    blockers = _blockers(evidence, selected)
    decision = _decision(evidence, blockers)
    command = (
        ".\\.venv\\Scripts\\python.exe examples\\run_paper_loop.py "
        f"--config {config_path} --state-dir {paper_state_dir} --candidate {selected}"
        if selected and decision == "PASS"
        else ""
    )
    return PaperCandidatePlan(
        decision=decision,
        candidate=selected,
        report_dir=str(root),
        paper_state_dir=str(paper_state_dir),
        command=command,
        required_evidence=evidence,
        blockers=blockers,
        notes=_notes(decision),
        prohibited_actions=[
            "Do not treat this as live trading approval.",
            "Do not connect a real broker from the paper loop command.",
            "Do not start paper observation from demo-only or stale data evidence.",
            "Do not change candidate, config, or capital without regenerating this plan.",
        ],
    )


def write_paper_candidate_plan(plan: PaperCandidatePlan, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "paper_candidate_plan.json").write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "paper_candidate_plan.md").write_text(plan.to_markdown(), encoding="utf-8")
    return root


def _required_evidence(root: Path, candidate: str) -> list[dict[str, str]]:
    checks = [
        ("run_manifest", "run_manifest.json", "PASS"),
        ("real_data_bootstrap", "real_data_bootstrap.json", "PASS"),
        ("real_data_gate", "real_data_gate.json", "PASS"),
        ("data_audit", "data_audit.json", "PASS"),
        ("robustness", "robustness_report.json", "PASS"),
        ("walk_forward", "walk_forward_report.json", "PASS"),
        ("candidate_walk_forward", "candidate_walk_forward_report.json", "PASS"),
        ("candidate_factor_diagnostics", "candidate_factor_diagnostics.json", "PASS"),
        ("candidate_regime_validation", "candidate_regime_validation_report.json", "PASS"),
        ("candidate_selection", "candidate_selection.json", "PASS"),
        ("llm_review", "llm_review.json", "PASS"),
        ("candidate_experiment_completion", "candidate_experiment_completion.json", "PASS"),
    ]
    evidence = []
    for name, artifact, desired in checks:
        path = root / artifact
        payload = _read_json(path)
        if name == "run_manifest":
            status, message = _manifest_status(path, payload)
        elif name == "candidate_experiment_completion":
            status, message = _completion_status(path, payload, candidate=candidate)
        else:
            status = _status(payload, default="BLOCK" if not path.exists() else "WATCH")
            message = ""
        evidence.append(
            {
                "name": name,
                "artifact": artifact,
                "status": status,
                "required": desired,
                "message": message,
            }
        )
    return evidence


def _blockers(evidence: list[dict[str, str]], candidate: str) -> list[str]:
    blockers = []
    if not candidate:
        blockers.append("No candidate is selected from candidate_selection.json.")
    for item in evidence:
        if item["status"] == "BLOCK":
            detail = item.get("message") or f"{item['name']} is BLOCK or missing ({item['artifact']})."
            blockers.append(detail)
    return blockers


def _decision(evidence: list[dict[str, str]], blockers: list[str]) -> PaperPlanDecision:
    if blockers:
        return "BLOCK"
    if any(item["status"] == "WATCH" for item in evidence):
        return "WATCH"
    return "PASS"


def _notes(decision: PaperPlanDecision) -> list[str]:
    if decision == "PASS":
        return [
            "Candidate may enter continuous paper observation only.",
            "Run the generated command on each trading day or schedule it manually.",
            "After 4-8 weeks, rerun weekly pipeline with --paper-state-dir.",
        ]
    if decision == "WATCH":
        return [
            "Candidate remains research-only while WATCH findings are unresolved.",
            "The plan intentionally withholds a paper loop command until every required evidence item is PASS.",
            "Do not promote to micro-live readiness while any WATCH evidence remains unresolved.",
        ]
    return [
        "Do not start or continue paper observation from this report directory.",
        "Fix BLOCK evidence first, usually data recency, data audit, walk-forward, or candidate validation.",
    ]


def _best_candidate(root: Path) -> str:
    payload = _read_json(root / "candidate_selection.json")
    return str(payload.get("selected_candidate") or payload.get("best_candidate", ""))


def _status(payload: dict[str, Any], *, default: str) -> PaperPlanDecision:
    raw = payload.get("status", payload.get("decision", default))
    text = str(raw).upper()
    if text == "PASS":
        return "PASS"
    if text == "WATCH":
        return "WATCH"
    return "BLOCK"


def _completion_status(
    path: Path,
    payload: dict[str, Any],
    *,
    candidate: str,
) -> tuple[PaperPlanDecision, str]:
    if not path.exists():
        return "BLOCK", "candidate_experiment_completion.json is missing; run completion review first."
    decision = str(payload.get("decision") or "").upper()
    if decision != "PASS":
        first = _first_text(payload.get("blockers")) or _first_text(payload.get("watch_items"))
        detail = f": {first}" if first else "."
        return "BLOCK", f"candidate_experiment_completion decision is {decision or 'UNKNOWN'}{detail}"
    selected = str(payload.get("selected_candidate") or "").strip()
    if candidate and selected and selected != candidate:
        return (
            "BLOCK",
            "candidate_experiment_completion selected_candidate mismatch: "
            f"{selected} != {candidate}.",
        )
    artifact_statuses = _completion_artifact_statuses(payload)
    for required in ("launch_contract", "launch_contract_evidence"):
        status = artifact_statuses.get(required, "MISSING")
        if status != "PASS":
            return (
                "BLOCK",
                f"candidate_experiment_completion {required} is {status}; paper entry requires PASS.",
            )
    return "PASS", "candidate_experiment_completion is PASS with launch contract evidence."


def _completion_artifact_statuses(payload: dict[str, Any]) -> dict[str, str]:
    artifacts = payload.get("artifacts", []) or []
    if not isinstance(artifacts, list):
        return {}
    out: dict[str, str] = {}
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if name:
            out[name] = str(item.get("status") or "UNKNOWN").upper()
    return out


def _first_text(value: object) -> str:
    if not isinstance(value, list) or not value:
        return ""
    return str(value[0])


def _manifest_status(path: Path, payload: dict[str, Any]) -> tuple[PaperPlanDecision, str]:
    if not path.exists():
        return "BLOCK", "run_manifest.json is missing; paper entry requires a traceable run manifest."
    if payload.get("demo_data_used") is True:
        return "BLOCK", "run_manifest.json says demo data was used."
    if not str(payload.get("in_sample_end", "") or "").strip():
        return "BLOCK", "run_manifest.json must record in_sample_end before paper entry."
    if not str(payload.get("out_sample_start", "") or "").strip():
        return "BLOCK", "run_manifest.json must record out_sample_start before paper entry."
    data_version = payload.get("data_version", {})
    if not isinstance(data_version, dict):
        return "BLOCK", "run_manifest.json data_version must contain source QA provenance."
    metadata = dict(data_version)
    metadata["data_source_qa_require_evidence_manifest"] = "true"
    blockers = cache_metadata_blockers(metadata)
    if blockers:
        return "BLOCK", f"run_manifest provenance blocker: {blockers[0]}"
    return "PASS", "run_manifest is PASS with sample split and source QA provenance."


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
