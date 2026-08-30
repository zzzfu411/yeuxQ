"""Plan whether a candidate is allowed to enter continuous paper observation."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quantify.data.cache_metadata import cache_metadata_blockers
from quantify.research.evidence_validation import (
    EvidenceContractValidation,
    validate_benchmark_payload,
    validate_multiple_testing_payload,
    validate_trial_registry_review_payload,
)
from quantify.research.selection_evidence import build_selection_evidence_manifest
from quantify.research.walk_forward_protocol import (
    CANDIDATE_WALK_FORWARD_ARTIFACT,
    WALK_FORWARD_ARTIFACT,
    validate_robustness_selection_safe_payload,
    validate_selection_safe_payload,
)

PaperPlanDecision = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class PaperCandidatePlan:
    decision: PaperPlanDecision
    candidate: str
    report_dir: str
    paper_state_dir: str
    cache_path: str
    cache_sha256: str
    dataset_fingerprint: str
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
            "cache_path": self.cache_path,
            "cache_sha256": self.cache_sha256,
            "dataset_fingerprint": self.dataset_fingerprint,
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
            f"- Research cache: `{self.cache_path or 'missing'}`",
            f"- Cache sha256: `{self.cache_sha256 or 'missing'}`",
            f"- Dataset fingerprint: `{self.dataset_fingerprint or 'missing'}`",
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
    manifest = _read_json(root / "run_manifest.json")
    cache_path, cache_sha256, dataset_fingerprint = _manifest_data_identity(manifest)
    evidence = _required_evidence(root, selected)
    blockers = _blockers(evidence, selected)
    decision = _decision(evidence, blockers)
    command = (
        ".\\.venv\\Scripts\\python.exe examples\\run_paper_loop.py "
        f"--config {_quote_path(config_path)} --cache {_quote_path(cache_path)} "
        f"--state-dir {_quote_path(paper_state_dir)} --candidate {selected} "
        f"--expected-cache-sha256 {cache_sha256} "
        f"--expected-dataset-fingerprint {dataset_fingerprint}"
        if selected and decision == "PASS"
        else ""
    )
    return PaperCandidatePlan(
        decision=decision,
        candidate=selected,
        report_dir=str(root),
        paper_state_dir=str(paper_state_dir),
        cache_path=cache_path,
        cache_sha256=cache_sha256,
        dataset_fingerprint=dataset_fingerprint,
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
        ("selection_evidence_manifest", "selection_evidence_manifest.json", "PASS"),
        ("benchmark", "benchmark_report.json", "PASS"),
        ("multiple_testing", "multiple_testing_report.json", "PASS"),
        ("trial_registry_review", "trial_registry_review.json", "PASS"),
        ("llm_review", "llm_review.json", "PASS"),
        ("candidate_experiment_completion", "candidate_experiment_completion.json", "PASS"),
    ]
    evidence = []
    for name, artifact, desired in checks:
        path = root / artifact
        payload = _read_json(path)
        if name == "run_manifest":
            status, message = _manifest_status(path, payload)
        elif name == "robustness":
            status, message = _robustness_status(path, payload)
        elif name == "candidate_experiment_completion":
            status, message = _completion_status(path, payload, candidate=candidate)
        elif name == "selection_evidence_manifest":
            status, message = _selection_manifest_status(root, path, payload)
        elif name in {"benchmark", "multiple_testing", "trial_registry_review"}:
            status, message = _statistical_evidence_status(
                root,
                name=name,
                payload=payload,
                candidate=candidate,
            )
        elif name in {"walk_forward", "candidate_walk_forward"}:
            status, message = _walk_forward_status(path, payload)
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


def _statistical_evidence_status(
    root: Path,
    *,
    name: str,
    payload: dict[str, Any],
    candidate: str,
) -> tuple[PaperPlanDecision, str]:
    manifest = _read_json(root / "run_manifest.json")
    parameters = manifest.get("research_parameters", {})
    expected_symbol = (
        str(parameters.get("index_code") or "") if isinstance(parameters, dict) else ""
    )
    validation: EvidenceContractValidation
    if name == "benchmark":
        validation = validate_benchmark_payload(payload, expected_symbol=expected_symbol)
    elif name == "multiple_testing":
        validation = validate_multiple_testing_payload(
            payload,
            expected_candidate=candidate,
        )
    else:
        validation = validate_trial_registry_review_payload(
            payload,
            expected_candidate=candidate,
            report_dir=root,
        )
    if not validation.valid:
        detail = "; ".join(validation.reasons) or "complete evidence contract is missing"
        return "BLOCK", f"{name} contract failed: {detail}"
    return validation.status, ""


def _robustness_status(
    path: Path,
    payload: dict[str, Any],
) -> tuple[PaperPlanDecision, str]:
    if not path.exists():
        return "BLOCK", "robustness_report.json is missing."
    validation = validate_robustness_selection_safe_payload(payload)
    if not validation.safe:
        return (
            "BLOCK",
            "robustness_report.json is diagnostic-only or fails the selection-safe contract: "
            + "; ".join(validation.reasons),
        )
    return _status(payload, default="WATCH"), ""


def _selection_manifest_status(
    root: Path,
    path: Path,
    payload: dict[str, Any],
) -> tuple[PaperPlanDecision, str]:
    if not path.exists():
        return "BLOCK", "selection_evidence_manifest.json is missing."
    current = build_selection_evidence_manifest(root)
    recorded_digest = str(payload.get("artifact_set_sha256") or "")
    if current.status == "BLOCK" or recorded_digest != current.artifact_set_sha256:
        detail = "; ".join(current.blockers) or "recorded artifact digest is stale"
        return "BLOCK", "Selection evidence manifest verification failed: " + detail
    recorded_status = _status(payload, default="BLOCK")
    if recorded_status != current.status:
        return "BLOCK", "Selection evidence manifest status does not match current artifacts."
    return recorded_status, ""


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


def _walk_forward_status(
    path: Path,
    payload: dict[str, Any],
) -> tuple[PaperPlanDecision, str]:
    if not path.exists():
        return _status(payload, default="BLOCK"), ""
    artifact_type = (
        CANDIDATE_WALK_FORWARD_ARTIFACT
        if path.name == "candidate_walk_forward_report.json"
        else WALK_FORWARD_ARTIFACT
    )
    validation = validate_selection_safe_payload(payload, artifact_type=artifact_type)
    if not validation.safe:
        return (
            "BLOCK",
            f"{path.name} does not satisfy the selection-safe v2 contract: "
            + "; ".join(validation.reasons),
        )
    return _status(payload, default="WATCH"), ""


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
    cache_path, cache_sha256, dataset_fingerprint = _manifest_data_identity(payload)
    if not cache_path:
        return "BLOCK", "run_manifest.json must record the research cache_path before paper entry."
    if not cache_sha256:
        return "BLOCK", "run_manifest.json must record the research cache_sha256 before paper entry."
    cache = Path(cache_path)
    if not cache.exists() or not cache.is_file():
        return "BLOCK", f"run_manifest research cache does not exist: {cache_path}."
    current_sha256 = _file_sha256(cache)
    if current_sha256 != cache_sha256:
        return "BLOCK", "run_manifest research cache_sha256 no longer matches the cache file."
    if not dataset_fingerprint:
        return "BLOCK", "run_manifest.json must record a dataset fingerprint before paper entry."
    data_version = payload.get("data_version", {})
    if not isinstance(data_version, dict):
        return "BLOCK", "run_manifest.json data_version must contain source QA provenance."
    metadata = dict(data_version)
    metadata["data_source_qa_require_evidence_manifest"] = "true"
    blockers = cache_metadata_blockers(metadata)
    if blockers:
        return "BLOCK", f"run_manifest provenance blocker: {blockers[0]}"
    return "PASS", "run_manifest is PASS with sample split and source QA provenance."


def _manifest_data_identity(payload: dict[str, Any]) -> tuple[str, str, str]:
    data_version = payload.get("data_version", {})
    if not isinstance(data_version, dict):
        data_version = {}
    fingerprint = str(
        data_version.get("csv_dataset_fingerprint")
        or data_version.get("raw_vendor_bars_sha256")
        or ""
    ).strip()
    return (
        str(payload.get("cache_path", "") or "").strip(),
        str(payload.get("cache_sha256", "") or "").strip(),
        fingerprint,
    )


def _quote_path(value: str | Path) -> str:
    return f'"{value}"'


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
