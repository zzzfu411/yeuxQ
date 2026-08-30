"""Goal-level evidence audit for the first-million compounding objective."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Literal

import pandas as pd

from quantify.data.cache_metadata import cache_metadata_blockers
from quantify.data.demo import is_demo_contaminated
from quantify.data.offline_package import format_source_provenance
from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.goal.planner import CapitalGoal
from quantify.research.evidence_validation import (
    EvidenceContractValidation,
    validate_benchmark_payload,
    validate_multiple_testing_payload,
    validate_trial_registry_review_payload,
)
from quantify.research.walk_forward_protocol import (
    CANDIDATE_WALK_FORWARD_ARTIFACT,
    WALK_FORWARD_ARTIFACT,
    validate_robustness_selection_safe_payload,
    validate_selection_safe_payload,
)

GoalStatusDecision = Literal["PASS", "WATCH", "BLOCK"]

STRATEGY_SEARCH_INPUT_GATES = {
    "data_cache",
    "recent_data_acquisition",
    "data_evidence_action_packet",
    "operator_handoff_status",
    "csv_intake_preview",
    "offline_source_qa_preflight",
    "offline_source_qa",
    "offline_import_doctor",
    "csv_validation",
    "offline_data_package",
    "offline_data_intake",
    "raw_vendor_traceability",
    "tdx_day_traceability",
    "run_manifest",
    "real_data_bootstrap",
    "real_data_gate",
    "data_coverage",
    "data_audit",
}


@dataclass(frozen=True, slots=True)
class GoalEvidenceItem:
    name: str
    status: GoalStatusDecision
    artifact: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "artifact": self.artifact,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class CapitalGoalStatus:
    decision: GoalStatusDecision
    goal: dict[str, float | int]
    report_dir: str
    best_candidate: str
    evidence: list[GoalEvidenceItem]
    blockers: list[str]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "goal": self.goal,
            "report_dir": self.report_dir,
            "best_candidate": self.best_candidate,
            "evidence": [item.to_dict() for item in self.evidence],
            "blockers": self.blockers,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Capital Goal Status: {self.decision}",
            "",
            f"- Report directory: `{self.report_dir}`",
            f"- Target capital: {float(self.goal['target_capital']):.2f}",
            f"- Starting capital: {float(self.goal['starting_capital']):.2f}",
            f"- Horizon years: {float(self.goal['years']):.1f}",
            f"- Required annual return: {float(self.goal['required_annual_return']):.2%}",
            f"- Best candidate: `{self.best_candidate or 'none'}`",
            "",
            "## Evidence Matrix",
            "",
            "| evidence | status | artifact | message |",
            "| --- | --- | --- | --- |",
        ]
        for item in self.evidence:
            lines.append(f"| {item.name} | `{item.status}` | `{item.artifact}` | {item.message} |")
        lines.extend(["", "## Blockers"])
        lines.extend(f"- {item}" for item in self.blockers) if self.blockers else lines.append(
            "- None."
        )
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_capital_goal_status(
    report_dir: str | Path,
    *,
    goal: CapitalGoal,
    cfg=None,
    source_qa_dir: str | Path | None = None,
    import_doctor_dir: str | Path | None = None,
    offline_intake_dir: str | Path | None = None,
    as_of: str | None = None,
    min_symbols: int = 300,
    min_trading_days: int = 240,
) -> CapitalGoalStatus:
    root = Path(report_dir)
    selected_candidate = _best_candidate(root)
    benchmark_symbol = _benchmark_symbol(root)
    evidence = [
        *(
            [
                _data_cache_status(
                    cfg, as_of=as_of, min_symbols=min_symbols, min_trading_days=min_trading_days
                )
            ]
            if cfg is not None
            else []
        ),
        _recent_data_acquisition_status(root),
        _provider_acquisition_ramp_status(root),
        _data_evidence_packet_status(root),
        _operator_handoff_status(root),
        _csv_intake_preview_status(root),
        *([_source_qa_preflight_status(Path(source_qa_dir))] if source_qa_dir is not None else []),
        *([_source_qa_status(Path(source_qa_dir))] if source_qa_dir is not None else []),
        *(
            [_import_doctor_status(Path(import_doctor_dir))]
            if import_doctor_dir is not None
            else []
        ),
        _csv_validation_status(root),
        _status_from_payload(
            root,
            "offline_data_package",
            "offline_data_package.json",
            status_key="status",
            block_when_missing=False,
            message_builder=_offline_data_package_message,
        ),
        *(
            [_offline_intake_status(Path(offline_intake_dir))]
            if offline_intake_dir is not None
            else []
        ),
        _raw_vendor_traceability_status(
            root,
            offline_intake_dir=Path(offline_intake_dir) if offline_intake_dir is not None else None,
            cfg=cfg,
        ),
        _tdx_day_traceability_status(
            root,
            offline_intake_dir=Path(offline_intake_dir) if offline_intake_dir is not None else None,
            cfg=cfg,
        ),
        _run_manifest_status(root),
        _status_from_payload(
            root, "real_data_bootstrap", "real_data_bootstrap.json", status_key="decision"
        ),
        _status_from_payload(root, "real_data_gate", "real_data_gate.json", status_key="decision"),
        _status_from_payload(root, "data_coverage", "data_coverage.json", status_key="status"),
        _status_from_payload(root, "data_audit", "data_audit.json", status_key="status"),
        _robustness_selection_safe_status(root),
        _selection_safe_status(
            root,
            "walk_forward",
            "walk_forward_report.json",
            artifact_type=WALK_FORWARD_ARTIFACT,
        ),
        _selection_safe_status(
            root,
            "candidate_walk_forward",
            "candidate_walk_forward_report.json",
            artifact_type=CANDIDATE_WALK_FORWARD_ARTIFACT,
        ),
        _status_from_payload(
            root,
            "candidate_factor_diagnostics",
            "candidate_factor_diagnostics.json",
            status_key="status",
        ),
        _status_from_payload(
            root,
            "candidate_regime_validation",
            "candidate_regime_validation_report.json",
            status_key="status",
        ),
        _candidate_launch_status(root),
        _candidate_execution_status(root),
        _candidate_completion_status(root),
        _candidate_selection_status(root, goal),
        _validated_statistical_evidence_status(
            root,
            "multiple_testing_report",
            "multiple_testing_report.json",
            expected_identity=selected_candidate,
            identity_label="deterministic selected candidate",
            validator=lambda payload: validate_multiple_testing_payload(
                payload,
                expected_candidate=selected_candidate,
            ),
        ),
        _validated_statistical_evidence_status(
            root,
            "benchmark_report",
            "benchmark_report.json",
            expected_identity=benchmark_symbol,
            identity_label="run_manifest.research_parameters.index_code",
            validator=lambda payload: validate_benchmark_payload(
                payload,
                expected_symbol=benchmark_symbol,
            ),
        ),
        _validated_statistical_evidence_status(
            root,
            "trial_registry_review",
            "trial_registry_review.json",
            expected_identity=selected_candidate,
            identity_label="deterministic selected candidate",
            validator=lambda payload: validate_trial_registry_review_payload(
                payload,
                expected_candidate=selected_candidate,
                report_dir=root,
            ),
        ),
        _status_from_payload(root, "llm_review", "llm_review.json", status_key="decision"),
        _status_from_payload(root, "paper_stability", "paper_stability.json", status_key="status"),
        _approval_status(root),
        _status_from_payload(
            root,
            "capital_scaling_plan",
            "capital_scaling_plan.json",
            status_key="decision",
            block_when_missing=False,
        ),
        _status_from_payload(
            root,
            "strategy_promotion_review",
            "strategy_promotion_review.json",
            status_key="decision",
        ),
    ]
    evidence.append(_strategy_search_gate(evidence))
    blockers = _blockers(evidence)
    decision = _combine([item.status for item in evidence])
    return CapitalGoalStatus(
        decision=decision,
        goal=goal.to_dict(),
        report_dir=str(root),
        best_candidate=_best_candidate(root),
        evidence=evidence,
        blockers=blockers,
        next_actions=_next_actions(evidence),
        prohibited_actions=[
            "Do not start strategy search or candidate experiments while the strategy_search_gate is BLOCK.",
            "Do not treat this status report as a promise of profit.",
            "Do not write profit-claim wording from candidate ranking or required-return math.",
            "Do not enter micro-live readiness while any evidence item is BLOCK.",
            "Do not use demo-only or stale data as capital-allocation evidence.",
            "Do not let LLM output override deterministic gates or human approval.",
            "Do not submit real broker orders from this system.",
        ],
    )


def write_capital_goal_status(status: CapitalGoalStatus, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "capital_goal_status.json").write_text(
        json.dumps(status.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "capital_goal_status.md").write_text(status.to_markdown(), encoding="utf-8")
    return root


def _status_from_payload(
    root: Path,
    name: str,
    artifact: str,
    *,
    status_key: str | None,
    block_when_missing: bool = True,
    message_builder=None,
) -> GoalEvidenceItem:
    path = root / artifact
    if not path.exists():
        missing_status: GoalStatusDecision = "BLOCK" if block_when_missing else "WATCH"
        return GoalEvidenceItem(
            name, missing_status, artifact, "Missing required evidence artifact."
        )
    payload = _read_json(path)
    status = "PASS" if status_key is None else _normalize_status(payload.get(status_key, "UNKNOWN"))
    message = message_builder(payload) if message_builder else _default_message(status, payload)
    return GoalEvidenceItem(name, status, artifact, message)


def _validated_statistical_evidence_status(
    root: Path,
    name: str,
    artifact: str,
    *,
    expected_identity: str,
    identity_label: str,
    validator: Callable[[dict[str, Any]], EvidenceContractValidation],
) -> GoalEvidenceItem:
    path = root / artifact
    if not path.exists():
        return GoalEvidenceItem(
            name,
            "BLOCK",
            artifact,
            f"Missing required statistical evidence artifact: {artifact}.",
        )
    payload = _read_json(path)
    if not payload:
        return GoalEvidenceItem(
            name,
            "BLOCK",
            artifact,
            f"Required statistical evidence {artifact} could not be parsed or is empty.",
        )
    if not expected_identity:
        return GoalEvidenceItem(
            name,
            "BLOCK",
            artifact,
            f"Cannot validate {artifact}: {identity_label} is missing.",
        )
    validation: EvidenceContractValidation = validator(payload)
    if not validation.valid:
        return GoalEvidenceItem(
            name,
            "BLOCK",
            artifact,
            f"{artifact} contract failed: " + "; ".join(validation.reasons),
        )
    return GoalEvidenceItem(
        name,
        validation.status,
        artifact,
        _statistical_evidence_message(name, validation.status, payload),
    )


def _selection_safe_status(
    root: Path,
    name: str,
    artifact: str,
    *,
    artifact_type: str,
) -> GoalEvidenceItem:
    path = root / artifact
    if not path.exists():
        return GoalEvidenceItem(name, "BLOCK", artifact, "Missing required evidence artifact.")
    payload = _read_json(path)
    validation = validate_selection_safe_payload(payload, artifact_type=artifact_type)
    if not validation.safe:
        return GoalEvidenceItem(
            name,
            "BLOCK",
            artifact,
            "Selection-safe v2 contract failed: " + "; ".join(validation.reasons),
        )
    status = _normalize_status(payload.get("status", "UNKNOWN"))
    return GoalEvidenceItem(name, status, artifact, _default_message(status, payload))


def _robustness_selection_safe_status(root: Path) -> GoalEvidenceItem:
    artifact = "robustness_report.json"
    path = root / artifact
    if not path.exists():
        return GoalEvidenceItem(
            "robustness", "BLOCK", artifact, "Missing required evidence artifact."
        )
    payload = _read_json(path)
    validation = validate_robustness_selection_safe_payload(payload)
    if not validation.safe:
        return GoalEvidenceItem(
            "robustness",
            "BLOCK",
            artifact,
            "Selection-safe robustness contract failed: " + "; ".join(validation.reasons),
        )
    status = _normalize_status(payload.get("status", "UNKNOWN"))
    return GoalEvidenceItem("robustness", status, artifact, _default_message(status, payload))


def _candidate_selection_status(root: Path, goal: CapitalGoal) -> GoalEvidenceItem:
    artifact = "candidate_selection.json"
    path = root / artifact
    if not path.exists():
        return GoalEvidenceItem(
            "candidate_selection", "BLOCK", artifact, "Missing candidate selection evidence."
        )
    payload = _read_json(path)
    status = _normalize_status(payload.get("status", "UNKNOWN"))
    best = str(payload.get("selected_candidate") or payload.get("best_candidate", ""))
    top = str(payload.get("top_candidate", ""))
    if not best:
        status = "BLOCK"
    candidates = payload.get("results", []) or []
    best_payload = next(
        (item for item in candidates if item.get("name") == best),
        candidates[0] if candidates else {},
    )
    metrics = best_payload.get("metrics", {}) or {}
    annual_return = _float(metrics.get("annualized_return"))
    required = goal.required_annual_return()
    if annual_return < required and status == "PASS":
        status = "WATCH"
    message = (
        f"Selected={best or 'none'}, top={top or best or 'none'}, annual_return={annual_return:.2%}, "
        f"required={required:.2%}; candidate ranking is research-only."
    )
    return GoalEvidenceItem("candidate_selection", status, artifact, message)


def _recent_data_acquisition_status(root: Path) -> GoalEvidenceItem:
    artifact = "recent_data_acquisition_plan.json"
    path = root / artifact
    if not path.exists():
        return GoalEvidenceItem(
            "recent_data_acquisition",
            "BLOCK",
            artifact,
            "Missing recent data acquisition plan; run it before strategy research.",
        )
    payload = _read_json(path)
    status = _normalize_status(payload.get("status", "UNKNOWN"))
    latest_import = payload.get("latest_import_attempt", {})
    latest_import = latest_import if isinstance(latest_import, dict) else {}
    if status == "PASS":
        latest = str(payload.get("current_latest_bar_date", "") or "missing")
        symbols = int(payload.get("current_symbol_count", 0) or 0)
        return GoalEvidenceItem(
            "recent_data_acquisition",
            "PASS",
            artifact,
            f"Recent data plan passed; latest_bar={latest}, symbols={symbols}.",
        )
    blockers = payload.get("blockers", []) or []
    first = str(blockers[0]) if blockers else "Recent data acquisition plan is not PASS."
    network = bool(latest_import.get("network_blocked"))
    actual_end = str(latest_import.get("actual_bar_end", "") or "missing")
    if network:
        first = f"{first} Latest AKShare attempt was network/proxy blocked; actual_bar_end={actual_end}."
    return GoalEvidenceItem("recent_data_acquisition", status, artifact, first)


def _provider_acquisition_ramp_status(root: Path) -> GoalEvidenceItem:
    artifact = "provider_acquisition_ramp.json"
    path = root / artifact
    if not path.exists():
        return GoalEvidenceItem(
            "provider_acquisition_ramp",
            "PASS",
            "not_applicable",
            "Provider acquisition ramp was not supplied; optional route diagnostics are not a data gate.",
        )
    payload = _read_json(path)
    raw_status = _normalize_status(payload.get("status", "UNKNOWN"))
    status: GoalStatusDecision = "PASS" if raw_status == "PASS" else "WATCH"
    provider = str(payload.get("provider") or "unknown")
    executed = int(payload.get("executed_stage_count") or len(payload.get("stages", []) or []))
    stages = [item for item in payload.get("stages", []) or [] if isinstance(item, dict)]
    last = stages[-1] if stages else {}
    imported = int(last.get("imported_symbols") or 0)
    requested = int(last.get("requested_symbols") or 0)
    if raw_status == "PASS":
        message = (
            f"Provider ramp passed for {provider}; executed_stages={executed}, "
            f"last_stage_imported={imported}/{requested}. Acquisition evidence only."
        )
    else:
        message = (
            f"Provider ramp is {raw_status}; route diagnostics only, "
            f"last_stage_imported={imported}/{requested}. It cannot approve source QA or promotion gates."
        )
    return GoalEvidenceItem("provider_acquisition_ramp", status, artifact, message)


def _data_evidence_packet_status(root: Path) -> GoalEvidenceItem:
    artifact = "data_evidence_action_packet.json"
    path = root / artifact
    if not path.exists():
        if (root / "data_gap_action_plan.json").exists():
            return GoalEvidenceItem(
                "data_evidence_action_packet",
                "BLOCK",
                artifact,
                "data_gap_action_plan.json exists but data_evidence_action_packet.json is missing.",
            )
        return GoalEvidenceItem(
            "data_evidence_action_packet",
            "PASS",
            "not_applicable",
            "No first-million data evidence action packet is required for this report directory.",
        )
    payload = _read_json(path)
    status = _normalize_status(payload.get("decision", "UNKNOWN"))
    blockers = payload.get("current_blockers", []) or []
    watches = payload.get("watch_items", []) or []
    bad = _first_named_payload(blockers, {"BLOCK"}) or _first_named_payload(watches, {"WATCH"})
    if bad:
        name = str(bad.get("name", "data_evidence"))
        message = str(bad.get("message", "data evidence action packet requires review."))
        next_action = str(bad.get("next_action", "") or "").strip()
        suffix = f" Next: {next_action}" if next_action else ""
        return GoalEvidenceItem(
            "data_evidence_action_packet",
            status,
            artifact,
            f"{name}: {message}{suffix}",
        )
    command_count = len(payload.get("immediate_commands", []) or [])
    evidence_count = len(payload.get("source_qa_evidence_to_fill", []) or [])
    return GoalEvidenceItem(
        "data_evidence_action_packet",
        status,
        artifact,
        f"Data evidence packet is {status}; immediate_commands={command_count}, source_evidence_items={evidence_count}.",
    )


def _operator_handoff_status(root: Path) -> GoalEvidenceItem:
    artifact = "operator_handoff_status.json"
    path = root / artifact
    if not path.exists():
        if (root / "operator_handoff.csv").exists() or (
            root / "data_evidence_action_packet.json"
        ).exists():
            return GoalEvidenceItem(
                "operator_handoff_status",
                "BLOCK",
                artifact,
                "operator_handoff_status.json is missing while operator handoff evidence exists.",
            )
        return GoalEvidenceItem(
            "operator_handoff_status",
            "PASS",
            "not_applicable",
            "No operator handoff queue is required for this report directory.",
        )
    payload = _read_json(path)
    status = _normalize_status(payload.get("status", "UNKNOWN"))
    open_count = int(payload.get("open_task_count", 0) or 0)
    p0_count = int(payload.get("p0_open_task_count", 0) or 0)
    source_count = int(payload.get("source_qa_open_task_count", 0) or 0)
    export_count = int(payload.get("data_export_open_task_count", 0) or 0)
    if open_count:
        message = (
            f"Operator handoff has {open_count} open tasks "
            f"(P0={p0_count}, source_qa={source_count}, data_export={export_count})."
        )
    else:
        message = (
            "Operator handoff queue has no open tasks; deterministic gates still decide readiness."
        )
    return GoalEvidenceItem("operator_handoff_status", status, artifact, message)


def _csv_intake_preview_status(root: Path) -> GoalEvidenceItem:
    artifact = "csv_intake_preview.json"
    path = root / artifact
    if not path.exists():
        if (root / "data_evidence_action_packet.json").exists() or (
            root / "offline_data_package.json"
        ).exists():
            return GoalEvidenceItem(
                "csv_intake_preview",
                "WATCH",
                artifact,
                "CSV intake preview is missing; column mapping evidence should be generated before guarded offline intake.",
            )
        return GoalEvidenceItem(
            "csv_intake_preview",
            "PASS",
            "not_applicable",
            "No CSV intake preview is required for this report directory.",
        )
    payload = _read_json(path)
    status = _normalize_status(payload.get("status", "UNKNOWN"))
    items = payload.get("items", []) or []
    bad = _first_named_payload(items, {"BLOCK"}) or _first_named_payload(items, {"WATCH"})
    if bad:
        file_name = str(bad.get("file_name", "csv"))
        message = str(bad.get("message", "CSV intake preview requires review."))
        missing = bad.get("missing_columns", []) or []
        suffix = f" Missing columns={','.join(str(item) for item in missing)}." if missing else ""
        return GoalEvidenceItem(
            "csv_intake_preview", status, artifact, f"{file_name}: {message}{suffix}"
        )
    bars = next(
        (item for item in items if isinstance(item, dict) and item.get("role") == "bars"), {}
    )
    return GoalEvidenceItem(
        "csv_intake_preview",
        status,
        artifact,
        (
            "CSV columns mapped for import preview; "
            f"bars_rows={bars.get('normalized_rows', 0)}, symbols={bars.get('symbol_count', 0)}."
        ),
    )


def _csv_validation_status(root: Path) -> GoalEvidenceItem:
    candidates = [
        root / "csv_validation.json",
        root / "offline_intake" / "csv_validation.json",
        Path("results") / "import" / "recent_csv_validation" / "csv_validation.json",
    ]
    path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    if not path.exists():
        return GoalEvidenceItem(
            "csv_validation",
            "WATCH",
            str(path),
            "Missing CSV validation report; validate offline exports before import.",
        )
    payload = _read_json(path)
    status = _normalize_status(payload.get("status", "UNKNOWN"))
    metrics = payload.get("metrics", {}) or {}
    message = (
        f"CSV validation {status}; bars_end={metrics.get('bars_end', 'missing')}, "
        f"lag_days={metrics.get('bars_end_lag_days', 'n/a')}, "
        f"symbols={metrics.get('bars_symbol_count', 0)}."
    )
    finding = _first_bad_finding(payload)
    if finding:
        message = f"{message} First finding={finding.get('code')}: {finding.get('message')}"
    return GoalEvidenceItem("csv_validation", status, str(path), message)


def _candidate_launch_status(root: Path) -> GoalEvidenceItem:
    artifact = "candidate_experiment_launch.json"
    path = root / artifact
    if not path.exists():
        return GoalEvidenceItem(
            "candidate_experiment_launch",
            "BLOCK",
            artifact,
            "Missing candidate experiment launch plan; run launch after readiness PASS.",
        )
    payload = _read_json(path)
    status = _normalize_status(payload.get("decision", "UNKNOWN"))
    if status == "PASS":
        candidate = str(payload.get("selected_candidate", ""))
        run_id = str(payload.get("run_id", ""))
        return GoalEvidenceItem(
            "candidate_experiment_launch",
            "PASS",
            artifact,
            f"Launch plan selected {candidate or 'none'} with run_id={run_id or 'none'}.",
        )
    blockers = payload.get("blocked_by", []) or []
    first = str(blockers[0]) if blockers else "Launch plan is BLOCK."
    return GoalEvidenceItem("candidate_experiment_launch", "BLOCK", artifact, first)


def _candidate_completion_status(root: Path) -> GoalEvidenceItem:
    artifact = "candidate_experiment_completion.json"
    path = root / artifact
    if not path.exists():
        return GoalEvidenceItem(
            "candidate_experiment_completion",
            "BLOCK",
            artifact,
            "Missing candidate experiment completion review; do not enter paper planning.",
        )
    payload = _read_json(path)
    status = _normalize_status(payload.get("decision", "UNKNOWN"))
    if status == "PASS":
        candidate = str(payload.get("selected_candidate", ""))
        run_id = str(payload.get("run_id", ""))
        return GoalEvidenceItem(
            "candidate_experiment_completion",
            "PASS",
            artifact,
            f"Experiment completion passed for {candidate or 'none'} with run_id={run_id or 'none'}.",
        )
    if status == "WATCH":
        watches = payload.get("watch_items", []) or []
        first = str(watches[0]) if watches else "Experiment completion has WATCH findings."
        return GoalEvidenceItem("candidate_experiment_completion", "WATCH", artifact, first)
    blockers = payload.get("blockers", []) or []
    first = str(blockers[0]) if blockers else "Experiment completion is BLOCK."
    return GoalEvidenceItem("candidate_experiment_completion", "BLOCK", artifact, first)


def _candidate_execution_status(root: Path) -> GoalEvidenceItem:
    artifact = "candidate_experiment_execution.json"
    path = root / artifact
    if not path.exists():
        return GoalEvidenceItem(
            "candidate_experiment_execution",
            "WATCH",
            artifact,
            "Missing candidate experiment execution report; dry-run or execute the launch plan before completion.",
        )
    payload = _read_json(path)
    decision = str(payload.get("decision", "UNKNOWN")).upper()
    if decision == "PASS":
        steps = payload.get("steps", []) or []
        return GoalEvidenceItem(
            "candidate_experiment_execution",
            "PASS",
            artifact,
            f"Executed candidate experiment commands; steps={len(steps)}.",
        )
    if decision == "DRY_RUN":
        steps = payload.get("steps", []) or []
        return GoalEvidenceItem(
            "candidate_experiment_execution",
            "WATCH",
            artifact,
            f"Launch commands validated in dry-run only; steps={len(steps)}.",
        )
    blockers = payload.get("blockers", []) or []
    first = str(blockers[0]) if blockers else "Candidate experiment execution is BLOCK."
    return GoalEvidenceItem("candidate_experiment_execution", "BLOCK", artifact, first)


def _approval_status(root: Path) -> GoalEvidenceItem:
    artifact = "approval_record.json"
    path = root / artifact
    if not path.exists():
        return GoalEvidenceItem(
            "human_approval",
            "BLOCK",
            artifact,
            "Missing human approval record; micro-live readiness cannot proceed.",
        )
    payload = _read_json(path)
    approved_by = str(payload.get("approved_by", "")).strip()
    allowed_stage = str(payload.get("allowed_stage", "")).strip()
    if approved_by and allowed_stage:
        return GoalEvidenceItem(
            "human_approval",
            "PASS",
            artifact,
            f"Approved by {approved_by}; allowed_stage={allowed_stage}.",
        )
    return GoalEvidenceItem("human_approval", "BLOCK", artifact, "Approval record is incomplete.")


def _import_doctor_status(path: Path) -> GoalEvidenceItem:
    artifact_path = path / "data_import_doctor.json" if path.suffix.lower() != ".json" else path
    if not artifact_path.exists():
        return GoalEvidenceItem(
            "offline_import_doctor",
            "WATCH",
            str(artifact_path),
            "Missing optional data import doctor report; run it before offline CSV import.",
        )
    payload = _read_json(artifact_path)
    status = _normalize_status(payload.get("status", "UNKNOWN"))
    findings = payload.get("findings", []) or []
    blocking = [
        finding for finding in findings if str(finding.get("severity", "")).upper() == "BLOCK"
    ]
    if blocking:
        first = blocking[0]
        code = str(first.get("code", "BLOCK"))
        message = str(first.get("message", "Offline import doctor is BLOCK."))
        return GoalEvidenceItem(
            "offline_import_doctor",
            "BLOCK",
            str(artifact_path),
            f"{code}: {message}",
        )
    if status == "WATCH":
        return GoalEvidenceItem(
            "offline_import_doctor",
            "WATCH",
            str(artifact_path),
            "Offline CSV exports have WATCH findings; review before import.",
        )
    return GoalEvidenceItem(
        "offline_import_doctor",
        "PASS",
        str(artifact_path),
        "Offline CSV exports passed the import doctor; import and bootstrap still required.",
    )


def _source_qa_status(path: Path) -> GoalEvidenceItem:
    artifact_path = path / "data_source_qa_review.json" if path.suffix.lower() != ".json" else path
    if not artifact_path.exists():
        return GoalEvidenceItem(
            "offline_source_qa",
            "WATCH",
            str(artifact_path),
            "Missing optional data source QA review; run it before guarded offline intake.",
        )
    payload = _read_json(artifact_path)
    status = _normalize_status(payload.get("status", "UNKNOWN"))
    findings = payload.get("findings", []) or []
    blocking = [
        finding for finding in findings if str(finding.get("severity", "")).upper() == "BLOCK"
    ]
    if blocking:
        first = blocking[0]
        code = str(first.get("code", "BLOCK"))
        message = str(first.get("message", "Data source QA is BLOCK."))
        return GoalEvidenceItem(
            "offline_source_qa", "BLOCK", str(artifact_path), f"{code}: {message}"
        )
    if status == "WATCH":
        first_watch = next(
            (
                finding
                for finding in findings
                if str(finding.get("severity", "")).upper() == "WATCH"
            ),
            {},
        )
        code = str(first_watch.get("code", "WATCH")) if first_watch else "WATCH"
        return GoalEvidenceItem(
            "offline_source_qa",
            "WATCH",
            str(artifact_path),
            f"{code}: Data source QA has WATCH findings; keep them with import evidence.",
        )
    return GoalEvidenceItem(
        "offline_source_qa",
        "PASS",
        str(artifact_path),
        "Data source QA review passed; CSV quality and bootstrap gates still required.",
    )


def _source_qa_preflight_status(path: Path) -> GoalEvidenceItem:
    artifact_path = _source_qa_preflight_artifact_path(path)
    if not artifact_path.exists():
        return GoalEvidenceItem(
            "offline_source_qa_preflight",
            "WATCH",
            str(artifact_path),
            "Missing optional source QA preflight; run it before guarded offline intake.",
        )
    payload = _read_json(artifact_path)
    status = _normalize_status(payload.get("status", "UNKNOWN"))
    items = payload.get("items", []) or []
    first_block = _first_item_with_status(items, "BLOCK")
    if first_block:
        return GoalEvidenceItem(
            "offline_source_qa_preflight",
            "BLOCK",
            str(artifact_path),
            _source_qa_preflight_item_message(first_block, "Source QA preflight is BLOCK."),
        )
    first_watch = _first_item_with_status(items, "WATCH")
    if status == "WATCH" or first_watch:
        return GoalEvidenceItem(
            "offline_source_qa_preflight",
            "WATCH",
            str(artifact_path),
            _source_qa_preflight_item_message(
                first_watch,
                "Source QA preflight has WATCH findings; preserve them with import evidence.",
            ),
        )
    if status == "BLOCK":
        return GoalEvidenceItem(
            "offline_source_qa_preflight",
            "BLOCK",
            str(artifact_path),
            "Source QA preflight is BLOCK; source-stage evidence is incomplete.",
        )
    return GoalEvidenceItem(
        "offline_source_qa_preflight",
        "PASS",
        str(artifact_path),
        "Source QA preflight has no unresolved source-stage gaps.",
    )


def _source_qa_preflight_artifact_path(path: Path) -> Path:
    if path.suffix.lower() != ".json":
        return path / "source_qa_preflight.json"
    if path.name == "source_qa_preflight.json":
        return path
    return path.parent / "source_qa_preflight.json"


def _offline_intake_status(path: Path) -> GoalEvidenceItem:
    artifact_path = path / "offline_data_intake.json" if path.suffix.lower() != ".json" else path
    if not artifact_path.exists():
        return GoalEvidenceItem(
            "offline_data_intake",
            "WATCH",
            str(artifact_path),
            "Missing optional guarded offline intake report; run it after replacing CSV templates.",
        )
    payload = _read_json(artifact_path)
    status = _normalize_status(payload.get("status", "UNKNOWN"))
    steps = payload.get("steps", []) or []
    if status == "BLOCK":
        first_block = _first_step_with_status(steps, "BLOCK")
        if first_block:
            return GoalEvidenceItem(
                "offline_data_intake",
                "BLOCK",
                str(artifact_path),
                f"Stopped at {first_block.get('name', 'unknown')}: {first_block.get('message', 'offline intake is BLOCK.')}",
            )
        return GoalEvidenceItem(
            "offline_data_intake",
            "BLOCK",
            str(artifact_path),
            "Guarded offline intake is BLOCK; do not run strategy research on this cache.",
        )
    if status == "WATCH":
        first_watch = _first_step_with_status(steps, "WATCH")
        detail = f" First WATCH step: {first_watch.get('name', 'unknown')}." if first_watch else ""
        return GoalEvidenceItem(
            "offline_data_intake",
            "WATCH",
            str(artifact_path),
            f"Guarded offline intake has WATCH findings; review before weekly research.{detail}",
        )
    return GoalEvidenceItem(
        "offline_data_intake",
        "PASS",
        str(artifact_path),
        "Guarded offline intake completed; cache/import/bootstrap evidence must still stay consistent.",
    )


def _raw_vendor_traceability_status(
    root: Path,
    *,
    offline_intake_dir: Path | None,
    cfg,
) -> GoalEvidenceItem:
    bases = _offline_intake_bases(root, offline_intake_dir)
    intake_path = _first_existing([base / "offline_data_intake.json" for base in bases])
    import_path = _first_existing([base / "data_import.json" for base in bases])
    normalization_path = _first_existing(
        [base / "vendor_bars_normalization.json" for base in bases]
    )
    manifest_path = _first_existing(
        [root / "run_manifest.json", root / "weekly" / "run_manifest.json"]
    )

    intake_payload = _read_json(intake_path) if intake_path else {}
    import_payload = _read_json(import_path) if import_path else {}
    normalization_payload = _read_json(normalization_path) if normalization_path else {}
    manifest_payload = _read_json(manifest_path) if manifest_path else {}

    import_metadata = import_payload.get("metadata", {}) if isinstance(import_payload, dict) else {}
    import_metadata = import_metadata if isinstance(import_metadata, dict) else {}
    manifest_version = (
        manifest_payload.get("data_version", {}) if isinstance(manifest_payload, dict) else {}
    )
    manifest_version = manifest_version if isinstance(manifest_version, dict) else {}

    raw_route_detected = (
        normalization_path is not None
        or _has_vendor_normalization_step(intake_payload)
        or bool(import_metadata.get("raw_vendor_bars_sha256"))
        or bool(manifest_version.get("raw_vendor_bars_sha256"))
    )
    if not raw_route_detected:
        return GoalEvidenceItem(
            "raw_vendor_traceability",
            "PASS",
            "not_applicable",
            "No raw vendor bars normalization evidence detected; standard CSV traceability applies.",
        )

    raw_hash = str(normalization_payload.get("raw_sha256", "") if normalization_payload else "")
    checks: list[str] = []
    warnings: list[str] = []
    if normalization_path is None:
        checks.append("vendor_bars_normalization.json is missing for a raw vendor CSV intake.")
    elif not raw_hash:
        checks.append("vendor_bars_normalization.json has no raw_sha256.")

    import_hash = str(import_metadata.get("raw_vendor_bars_sha256", "") or "")
    if import_path is None:
        checks.append("data_import.json is missing; raw vendor hash did not reach import metadata.")
    elif not import_hash:
        checks.append("data_import.json metadata has no raw_vendor_bars_sha256.")
    elif raw_hash and import_hash != raw_hash:
        checks.append("data_import.json metadata raw_vendor_bars_sha256 does not match raw_sha256.")

    manifest_hash = str(manifest_version.get("raw_vendor_bars_sha256", "") or "")
    if manifest_path is None:
        checks.append(
            "run_manifest.json is missing; raw vendor hash cannot be tied to research runs."
        )
    elif not manifest_hash:
        checks.append("run_manifest data_version has no raw_vendor_bars_sha256.")
    elif raw_hash and manifest_hash != raw_hash:
        checks.append("run_manifest data_version raw_vendor_bars_sha256 does not match raw_sha256.")

    cache_metadata = _cache_metadata(cfg)
    if cache_metadata is None:
        warnings.append(
            "SQLite research_metadata was not checked because config/cache evidence is unavailable."
        )
    else:
        cache_hash = str(cache_metadata.get("raw_vendor_bars_sha256", "") or "")
        if not cache_hash:
            checks.append("SQLite research_metadata has no raw_vendor_bars_sha256.")
        elif raw_hash and cache_hash != raw_hash:
            checks.append(
                "SQLite research_metadata raw_vendor_bars_sha256 does not match raw_sha256."
            )

    artifact = str(
        normalization_path
        or import_path
        or intake_path
        or manifest_path
        or "raw_vendor_traceability"
    )
    if checks:
        return GoalEvidenceItem("raw_vendor_traceability", "BLOCK", artifact, checks[0])
    if warnings:
        return GoalEvidenceItem("raw_vendor_traceability", "WATCH", artifact, warnings[0])
    return GoalEvidenceItem(
        "raw_vendor_traceability",
        "PASS",
        artifact,
        f"Raw vendor bars sha256 {raw_hash[:12]}... is consistent across normalization, import metadata, cache metadata, and run manifest.",
    )


def _tdx_day_traceability_status(
    root: Path,
    *,
    offline_intake_dir: Path | None,
    cfg,
) -> GoalEvidenceItem:
    bases = _offline_intake_bases(root, offline_intake_dir)
    import_path = _first_existing([base / "data_import.json" for base in bases])
    manifest_path = _first_existing(
        [root / "run_manifest.json", root / "weekly" / "run_manifest.json"]
    )

    import_payload = _read_json(import_path) if import_path else {}
    manifest_payload = _read_json(manifest_path) if manifest_path else {}
    import_metadata = import_payload.get("metadata", {}) if isinstance(import_payload, dict) else {}
    import_metadata = import_metadata if isinstance(import_metadata, dict) else {}
    manifest_version = (
        manifest_payload.get("data_version", {}) if isinstance(manifest_payload, dict) else {}
    )
    manifest_version = manifest_version if isinstance(manifest_version, dict) else {}
    cache_metadata = _cache_metadata(cfg)

    tdx_route_detected = any(
        _has_tdx_day_metadata(payload)
        for payload in [import_metadata, manifest_version, cache_metadata or {}]
    )
    if not tdx_route_detected:
        return GoalEvidenceItem(
            "tdx_day_traceability",
            "PASS",
            "not_applicable",
            "No TongDaXin .day export evidence detected; standard CSV traceability applies.",
        )

    checks: list[str] = []
    warnings: list[str] = []
    report_path = _tdx_report_path(import_metadata, manifest_version, cache_metadata or {})
    report_payload = _read_json(report_path) if report_path else {}
    report_hash = _file_sha256(report_path) if report_path and report_path.exists() else ""
    if report_path is None:
        checks.append("tdx_day_export_report is missing from TDX import/cache/run metadata.")
    elif not report_path.exists():
        checks.append(f"tdx_day_export_report does not exist: {report_path}.")
    elif _normalize_status(report_payload.get("status", "UNKNOWN")) == "BLOCK":
        checks.append("tdx_day_export.json is BLOCK and cannot support imported research evidence.")
    elif _normalize_status(report_payload.get("status", "UNKNOWN")) == "WATCH":
        warnings.append("tdx_day_export.json has WATCH findings; review converted file coverage.")

    expected = _tdx_expected_metadata(report_payload) if report_payload else {}
    if import_path is None:
        checks.append(
            "data_import.json is missing; TDX export evidence did not reach import metadata."
        )
    else:
        checks.extend(
            _tdx_metadata_checks(
                "data_import.json metadata",
                import_metadata,
                report_hash=report_hash,
                expected=expected,
            )
        )
    if manifest_path is None:
        checks.append(
            "run_manifest.json is missing; TDX export evidence cannot be tied to research runs."
        )
    else:
        checks.extend(
            _tdx_metadata_checks(
                "run_manifest data_version",
                manifest_version,
                report_hash=report_hash,
                expected=expected,
            )
        )
    if cache_metadata is None:
        warnings.append(
            "SQLite research_metadata was not checked because config/cache evidence is unavailable."
        )
    else:
        checks.extend(
            _tdx_metadata_checks(
                "SQLite research_metadata",
                cache_metadata,
                report_hash=report_hash,
                expected=expected,
            )
        )

    artifact = str(report_path or import_path or manifest_path or "tdx_day_traceability")
    if checks:
        return GoalEvidenceItem("tdx_day_traceability", "BLOCK", artifact, checks[0])
    if warnings:
        return GoalEvidenceItem("tdx_day_traceability", "WATCH", artifact, warnings[0])
    return GoalEvidenceItem(
        "tdx_day_traceability",
        "PASS",
        artifact,
        f"TDX day export sha256 {report_hash[:12]}... is consistent across export report, import metadata, cache metadata, and run manifest.",
    )


def _data_cache_status(
    cfg,
    *,
    as_of: str | None,
    min_symbols: int,
    min_trading_days: int,
) -> GoalEvidenceItem:
    cache = Path(str(cfg.data.cache_path))
    if not cache.exists():
        return GoalEvidenceItem(
            "data_cache",
            "BLOCK",
            str(cache),
            "Configured research cache does not exist; import recent real A-share data first.",
        )
    storage = BarStorage(cache)
    provider = DataProvider(storage)
    gate = _evaluate_cache_gate(
        provider,
        str(cfg.research.start),
        str(cfg.research.end),
        as_of=as_of,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
    )
    message = (
        f"cache={cache}, latest_bar={gate['latest_bar_date'] or 'missing'}, "
        f"symbols={gate['symbol_count']}, trading_days={gate['trading_day_count']}, "
        f"bars={gate['bar_count']}, demo={gate['demo_data_used']}."
    )
    metadata_blockers = cache_metadata_blockers(storage.load_metadata())
    if gate["decision"] == "PASS" and metadata_blockers:
        return GoalEvidenceItem(
            "data_cache",
            "BLOCK",
            str(cache),
            f"{message} Cache metadata blocker: {metadata_blockers[0]}",
        )
    return GoalEvidenceItem("data_cache", gate["decision"], str(cache), message)


def _run_manifest_status(root: Path) -> GoalEvidenceItem:
    artifact = "run_manifest.json"
    path = root / artifact
    if not path.exists():
        return GoalEvidenceItem(
            "run_manifest", "BLOCK", artifact, "Missing required evidence artifact."
        )
    payload = _read_json(path)
    status: GoalStatusDecision = "PASS"
    data_version = payload.get("data_version", {}) if isinstance(payload, dict) else {}
    data_version = data_version if isinstance(data_version, dict) else {}
    if (
        bool(payload.get("demo_data_used", False))
        or not str(data_version.get("csv_dataset_fingerprint", "") or "").strip()
    ):
        status = "BLOCK"
    return GoalEvidenceItem("run_manifest", status, artifact, _manifest_message(payload))


def _strategy_search_gate(evidence: list[GoalEvidenceItem]) -> GoalEvidenceItem:
    input_gates = [item for item in evidence if item.name in STRATEGY_SEARCH_INPUT_GATES]
    blockers = [item for item in input_gates if item.status == "BLOCK"]
    if blockers:
        first = next(
            (item for item in blockers if item.name == "data_evidence_action_packet"),
            blockers[0],
        )
        return GoalEvidenceItem(
            "strategy_search_gate",
            "BLOCK",
            "derived:capital_goal_status",
            (
                f"Closed by {first.name}: {first.message} Do not enter strategy search, "
                "candidate experiments, or profit-claim wording until data/source gates PASS."
            ),
        )
    watches = [item for item in input_gates if item.status == "WATCH"]
    if watches:
        first = watches[0]
        return GoalEvidenceItem(
            "strategy_search_gate",
            "WATCH",
            "derived:capital_goal_status",
            (
                f"Guarded by {first.name}: {first.message} Keep any strategy output research-only "
                "and avoid profit-claim wording."
            ),
        )
    return GoalEvidenceItem(
        "strategy_search_gate",
        "PASS",
        "derived:capital_goal_status",
        "Data/source gates are PASS for research-only strategy search; this is not a profit promise.",
    )


def _evaluate_cache_gate(
    data: DataProvider,
    start: str,
    end: str,
    *,
    as_of: str | None,
    min_symbols: int,
    min_trading_days: int,
    max_staleness_days: int = 10,
) -> dict[str, Any]:
    symbols = data.all_symbols()
    days = data.trading_days(start, end)
    bars = data.bars(symbols, start, end) if symbols else pd.DataFrame()
    latest_bar = _latest_bar_date(bars)
    as_of_date = pd.Timestamp(as_of or date.today().isoformat()).date()
    staleness = (as_of_date - pd.Timestamp(latest_bar).date()).days if latest_bar else None
    demo = is_demo_contaminated(symbols)
    statuses: list[GoalStatusDecision] = []
    if not symbols or bars.empty or demo or staleness is None or staleness > max_staleness_days:
        statuses.append("BLOCK")
    if (
        len(symbols) < min_symbols
        or len(days) < min_trading_days
        or (staleness is not None and staleness < 0)
    ):
        statuses.append("WATCH")
    return {
        "decision": _combine(statuses),
        "latest_bar_date": latest_bar,
        "symbol_count": len(symbols),
        "trading_day_count": len(days),
        "bar_count": len(bars),
        "demo_data_used": demo,
    }


def _latest_bar_date(bars: pd.DataFrame) -> str:
    if bars.empty or "date" not in bars:
        return ""
    values = pd.to_datetime(bars["date"], errors="coerce").dropna()
    if values.empty:
        return ""
    return values.max().date().isoformat()


def _manifest_message(payload: dict[str, Any]) -> str:
    demo = bool(payload.get("demo_data_used", False))
    latest = str(payload.get("latest_bar_date", ""))
    data_version = payload.get("data_version", {}) or {}
    fingerprint = str(data_version.get("csv_dataset_fingerprint", ""))
    raw_hash = str(data_version.get("raw_vendor_bars_sha256", ""))
    tdx_hash = str(data_version.get("tdx_day_export_sha256", ""))
    if demo:
        return "Run manifest exists but demo_data_used=true; cannot support capital-goal promotion."
    links = []
    if fingerprint:
        links.append(f"CSV fingerprint {fingerprint[:12]}...")
    if raw_hash:
        links.append(f"raw vendor hash {raw_hash[:12]}...")
    if tdx_hash:
        links.append(f"TDX day export sha256 {tdx_hash[:12]}...")
    if links:
        return f"Run manifest links cache/config to {', '.join(links)}, latest_bar={latest or 'missing'}."
    return f"Run manifest exists, but no CSV dataset fingerprint is recorded; latest_bar={latest or 'missing'}."


def _default_message(status: GoalStatusDecision, payload: dict[str, Any]) -> str:
    if status == "PASS":
        return "Evidence gate is PASS."
    if status == "WATCH":
        return "Evidence gate has WATCH findings; continue research or paper observation."
    findings = payload.get("findings", []) or payload.get("issues", []) or []
    if findings:
        first = findings[0]
        if isinstance(first, dict):
            return str(first.get("message") or first.get("code") or "Evidence gate is BLOCK.")
    return "Evidence gate is BLOCK or missing required pass conditions."


def _statistical_evidence_message(
    name: str,
    status: GoalStatusDecision,
    payload: dict[str, Any],
) -> str:
    if name == "multiple_testing_report":
        input_payload = payload.get("input", {}) or {}
        parameters = payload.get("parameters", {}) or {}
        return (
            f"Multiple-testing evidence is {status}; candidate="
            f"{parameters.get('selected_candidate', 'none') or 'none'}, "
            f"trials={len(input_payload.get('candidate_columns', []) or [])}, "
            f"observations={input_payload.get('observations', 'unknown')}."
        )
    if name == "benchmark_report":
        identity = payload.get("identity", {}) or {}
        alignment = payload.get("alignment", {}) or {}
        return (
            f"Benchmark evidence is {status}; symbol={identity.get('symbol', 'none') or 'none'}, "
            f"total_return={identity.get('total_return', 'unknown')}, "
            f"aligned_observations={alignment.get('aligned_observations', 'unknown')}."
        )
    return (
        f"Trial registry review is {status}; candidate="
        f"{payload.get('selected_candidate', 'none') or 'none'}, "
        f"trial_id={payload.get('matched_trial_id', 'none') or 'none'}, "
        f"verified_events={payload.get('verified_event_count', 'unknown')}."
    )


def _offline_data_package_message(payload: dict[str, Any]) -> str:
    items = payload.get("items", []) or []
    bad = [
        item
        for item in items
        if isinstance(item, dict) and str(item.get("status", "")).upper() in {"BLOCK", "WATCH"}
    ]
    if bad:
        first = bad[0]
        return f"{first.get('name', 'item')}: {first.get('message', 'offline data package requires review.')}"
    provenance = format_source_provenance(_dict_payload(payload.get("source_metadata_summary")))
    if provenance:
        return f"Offline data package passed source, inventory, template, and doctor checks; {provenance}."
    return "Offline data package passed source, inventory, template, and doctor checks."


def _best_candidate(root: Path) -> str:
    payload = _read_json(root / "candidate_selection.json")
    return str(payload.get("selected_candidate") or payload.get("best_candidate", ""))


def _benchmark_symbol(root: Path) -> str:
    payload = _read_json(root / "run_manifest.json")
    parameters = payload.get("research_parameters")
    if not isinstance(parameters, dict):
        return ""
    return str(parameters.get("index_code") or "").strip()


def _blockers(evidence: list[GoalEvidenceItem]) -> list[str]:
    return [f"{item.name}: {item.message}" for item in evidence if item.status == "BLOCK"]


def _next_actions(evidence: list[GoalEvidenceItem]) -> list[str]:
    actions = []
    status_by_name = {item.name: item.status for item in evidence}
    item_by_name = {item.name: item for item in evidence}
    if status_by_name.get("data_cache") == "BLOCK":
        data_cache = item_by_name.get("data_cache")
        metadata_only_cache_block = (
            data_cache is not None and "Cache metadata blocker:" in data_cache.message
        )
        data_packet = item_by_name.get("data_evidence_action_packet")
        if data_packet is not None and data_packet.status == "BLOCK":
            actions.append(f"Follow data evidence action packet first: {data_packet.message}")
        acquisition = item_by_name.get("recent_data_acquisition")
        csv_validation = item_by_name.get("csv_validation")
        csv_preview = item_by_name.get("csv_intake_preview")
        if not metadata_only_cache_block:
            if acquisition is not None and acquisition.status == "BLOCK":
                actions.append(f"Fix recent data acquisition first: {acquisition.message}")
            if csv_preview is not None and csv_preview.status == "BLOCK":
                actions.append(f"Fix CSV intake preview first: {csv_preview.message}")
            if csv_validation is not None and csv_validation.status == "BLOCK":
                actions.append(f"Fix CSV validation blocker first: {csv_validation.message}")
        source_qa_preflight = item_by_name.get("offline_source_qa_preflight")
        source_qa = item_by_name.get("offline_source_qa")
        intake = item_by_name.get("offline_data_intake")
        doctor = item_by_name.get("offline_import_doctor")
        if source_qa_preflight is not None and source_qa_preflight.status == "BLOCK":
            actions.append(f"Fix source QA preflight blocker first: {source_qa_preflight.message}")
        elif source_qa is not None and source_qa.status == "BLOCK":
            actions.append(f"Fix data source QA blocker first: {source_qa.message}")
        elif intake is not None and intake.status == "BLOCK":
            actions.append(f"Fix offline data intake blocker first: {intake.message}")
        elif status_by_name.get("raw_vendor_traceability") == "BLOCK":
            raw_trace = item_by_name.get("raw_vendor_traceability")
            actions.append(
                f"Fix raw vendor traceability blocker first: {raw_trace.message if raw_trace else 'raw traceability is BLOCK.'}"
            )
        elif status_by_name.get("tdx_day_traceability") == "BLOCK":
            tdx_trace = item_by_name.get("tdx_day_traceability")
            actions.append(
                f"Fix TDX day traceability blocker first: {tdx_trace.message if tdx_trace else 'TDX traceability is BLOCK.'}"
            )
        elif source_qa_preflight is not None and source_qa_preflight.status == "WATCH":
            actions.append("Review source QA preflight WATCH findings before importing CSV data.")
        elif source_qa is not None and source_qa.status == "WATCH":
            actions.append("Review data source QA WATCH findings before importing CSV data.")
        elif doctor is not None and doctor.status == "BLOCK":
            actions.append(f"Fix offline import doctor blocker first: {doctor.message}")
        elif csv_preview is not None and csv_preview.status == "WATCH":
            actions.append(
                f"Review CSV intake preview WATCH item before importing data: {csv_preview.message}"
            )
        elif status_by_name.get("offline_data_package") == "BLOCK":
            package = item_by_name.get("offline_data_package")
            actions.append(
                f"Fix offline data package blocker first: {package.message if package else 'package is BLOCK.'}"
            )
        elif intake is not None and intake.status == "WATCH":
            actions.append(
                "Review guarded offline intake WATCH findings before running strategy research."
            )
        elif status_by_name.get("offline_data_package") == "WATCH":
            actions.append("Review offline data package WATCH findings before importing CSV data.")
        elif doctor is not None and doctor.status == "WATCH":
            actions.append("Review offline import doctor WATCH findings before importing CSV data.")
        elif data_packet is not None and data_packet.status == "WATCH":
            actions.append(
                f"Review data evidence action packet WATCH item before importing data: {data_packet.message}"
            )
        if metadata_only_cache_block:
            actions.append(
                "Rerun guarded offline intake so the cache records CSV fingerprint, PASS source QA metadata, and provenance hashes."
            )
            actions.append(
                "Rerun run_manifest and real_data_bootstrap after cache metadata is repaired."
            )
            return actions
        actions.append(
            "Import recent real A-share data into the configured cache before running research."
        )
        actions.append("Rerun real_data_bootstrap after the cache has broad, recent daily bars.")
        return actions
    if status_by_name.get("data_evidence_action_packet") == "BLOCK":
        packet = item_by_name.get("data_evidence_action_packet")
        actions.append(
            f"Follow data evidence action packet first: {packet.message if packet else 'packet is BLOCK.'}"
        )
    if status_by_name.get("operator_handoff_status") == "BLOCK":
        handoff = item_by_name.get("operator_handoff_status")
        actions.append(
            f"Close operator handoff P0 tasks first: {handoff.message if handoff else 'operator handoff is BLOCK.'}"
        )
    if status_by_name.get("csv_intake_preview") == "BLOCK":
        csv_preview = item_by_name.get("csv_intake_preview")
        actions.append(
            f"Fix csv_intake_preview.md before strategy search: {csv_preview.message if csv_preview else 'CSV preview is BLOCK.'}"
        )
    if status_by_name.get("strategy_search_gate") == "BLOCK":
        gate = item_by_name.get("strategy_search_gate")
        actions.append(
            f"Keep strategy search closed until data/source gates pass: {gate.message if gate else 'gate is BLOCK.'}"
        )
    if status_by_name.get("raw_vendor_traceability") == "BLOCK":
        raw_trace = item_by_name.get("raw_vendor_traceability")
        actions.append(
            f"Repair raw vendor traceability and CSV fingerprint chain before strategy search: {raw_trace.message if raw_trace else 'raw traceability is BLOCK.'}"
        )
    if status_by_name.get("raw_vendor_traceability") == "WATCH":
        actions.append(
            "Provide config/cache evidence so raw vendor CSV fingerprint can be checked in SQLite metadata."
        )
    if status_by_name.get("tdx_day_traceability") == "BLOCK":
        tdx_trace = item_by_name.get("tdx_day_traceability")
        actions.append(
            f"Repair TDX day export traceability before strategy search: {tdx_trace.message if tdx_trace else 'TDX traceability is BLOCK.'}"
        )
    if status_by_name.get("tdx_day_traceability") == "WATCH":
        actions.append(
            "Review TDX day export WATCH evidence and provide config/cache metadata if missing."
        )
    if status_by_name.get("data_evidence_action_packet") == "WATCH":
        packet = item_by_name.get("data_evidence_action_packet")
        actions.append(
            f"Review data_evidence_action_packet.md WATCH item before strategy search: {packet.message if packet else 'packet is WATCH.'}"
        )
    if status_by_name.get("csv_intake_preview") == "WATCH":
        csv_preview = item_by_name.get("csv_intake_preview")
        actions.append(
            f"Review csv_intake_preview.md WATCH item before strategy search: {csv_preview.message if csv_preview else 'CSV preview is WATCH.'}"
        )
    if status_by_name.get("operator_handoff_status") == "WATCH":
        handoff = item_by_name.get("operator_handoff_status")
        actions.append(
            f"Review operator handoff WATCH items before strategy search: {handoff.message if handoff else 'operator handoff is WATCH.'}"
        )
    if status_by_name.get("provider_acquisition_ramp") == "WATCH":
        ramp = item_by_name.get("provider_acquisition_ramp")
        actions.append(
            f"Review provider acquisition ramp route diagnostics before scaling provider imports: {ramp.message if ramp else 'provider ramp is WATCH.'}"
        )
    if status_by_name.get("run_manifest") == "BLOCK":
        actions.append("Re-run research or weekly pipeline to generate run_manifest.json/md.")
    if status_by_name.get("real_data_bootstrap") == "BLOCK":
        actions.append("Import recent real A-share data, then rerun real_data_bootstrap.")
    if status_by_name.get("data_audit") == "BLOCK":
        actions.append("Fix data quality issues before strategy evaluation.")
    if status_by_name.get("candidate_walk_forward") == "BLOCK":
        actions.append("Run candidate walk-forward validation on real recent data.")
    if status_by_name.get("candidate_factor_diagnostics") == "BLOCK":
        actions.append("Run candidate factor diagnostics to check single-factor dependency.")
    if status_by_name.get("candidate_regime_validation") == "BLOCK":
        actions.append("Run candidate regime validation and include adverse market windows.")
    if status_by_name.get("candidate_experiment_launch") == "BLOCK":
        actions.append(
            "Run candidate experiment launch only after readiness, source QA, and offline intake are PASS."
        )
    if status_by_name.get("candidate_experiment_execution") == "BLOCK":
        actions.append("Fix candidate experiment execution before reviewing completion.")
    if status_by_name.get("candidate_experiment_execution") == "WATCH":
        actions.append(
            "Run the guarded candidate experiment executor without --dry-run before completion review."
        )
    if status_by_name.get("candidate_experiment_completion") == "BLOCK":
        actions.append("Complete every required candidate experiment output before paper planning.")
    if status_by_name.get("candidate_experiment_completion") == "WATCH":
        actions.append("Review candidate experiment completion WATCH items before paper planning.")
    for name, label in (
        ("multiple_testing_report", "multiple-testing report"),
        ("benchmark_report", "benchmark report"),
        ("trial_registry_review", "trial registry review"),
    ):
        item = item_by_name.get(name)
        if item is None or item.status == "PASS":
            continue
        if item.status == "BLOCK":
            actions.append(
                f"Repair the required {label} and rerun contract validation: {item.message}"
            )
        else:
            actions.append(
                f"Resolve WATCH findings in the {label} before promotion: {item.message}"
            )
    if status_by_name.get("paper_stability") == "BLOCK":
        actions.append("Run paper loop for 4-8 weeks and generate paper_stability.json/md.")
    if status_by_name.get("human_approval") == "BLOCK":
        actions.append(
            "Do not proceed to micro-live readiness until a complete approval_record.json exists."
        )
    if not actions:
        actions.append(
            "Continue weekly evidence accumulation; do not increase capital without a fresh review."
        )
    return actions


def _combine(statuses: list[GoalStatusDecision]) -> GoalStatusDecision:
    if any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    if any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"


def _normalize_status(value: object) -> GoalStatusDecision:
    text = str(value).upper()
    if text == "PASS":
        return "PASS"
    if text == "WATCH":
        return "WATCH"
    return "BLOCK"


def _first_step_with_status(steps: list[Any], status: GoalStatusDecision) -> dict[str, Any]:
    for step in steps:
        if isinstance(step, dict) and _normalize_status(step.get("status", "UNKNOWN")) == status:
            return step
    return {}


def _first_item_with_status(items: list[Any], status: GoalStatusDecision) -> dict[str, Any]:
    for item in items:
        if isinstance(item, dict) and _normalize_status(item.get("status", "UNKNOWN")) == status:
            return item
    return {}


def _source_qa_preflight_item_message(item: dict[str, Any], default: str) -> str:
    field = str(item.get("field") or item.get("name") or item.get("code") or "").strip()
    message = str(item.get("message") or default).strip()
    return f"{field}: {message}" if field else message


def _first_bad_finding(payload: dict[str, Any]) -> dict[str, Any]:
    for finding in payload.get("findings", []) or []:
        if isinstance(finding, dict) and str(finding.get("severity", "")).upper() in {
            "BLOCK",
            "WATCH",
        }:
            return finding
    return {}


def _first_named_payload(items: list[Any], statuses: set[str]) -> dict[str, Any]:
    for item in items:
        if isinstance(item, dict) and str(item.get("status", "")).upper() in statuses:
            return item
    return {}


def _offline_intake_bases(root: Path, offline_intake_dir: Path | None) -> list[Path]:
    bases: list[Path] = []
    if offline_intake_dir is not None:
        bases.append(
            offline_intake_dir.parent
            if offline_intake_dir.suffix.lower() == ".json"
            else offline_intake_dir
        )
    bases.extend([root / "offline_intake", root])
    result: list[Path] = []
    for base in bases:
        if base not in result:
            result.append(base)
    return result


def _first_existing(paths: list[Path]) -> Path | None:
    return next((path for path in paths if path.exists()), None)


def _has_vendor_normalization_step(payload: dict[str, Any]) -> bool:
    steps = payload.get("steps", []) if isinstance(payload, dict) else []
    return any(
        isinstance(step, dict) and str(step.get("name", "")) == "vendor_bars_normalization"
        for step in steps
    )


def _has_tdx_day_metadata(payload: dict[str, Any]) -> bool:
    return any(
        str(payload.get(key, "") or "").strip()
        for key in (
            "tdx_day_export_report",
            "tdx_day_export_sha256",
            "tdx_day_input_dir",
            "tdx_day_symbol_count",
            "tdx_day_row_count",
        )
    )


def _tdx_report_path(*payloads: dict[str, Any]) -> Path | None:
    for payload in payloads:
        value = str(payload.get("tdx_day_export_report", "") or "").strip()
        if value:
            return Path(value)
    return None


def _tdx_expected_metadata(report: dict[str, Any]) -> dict[str, str]:
    return {
        "tdx_day_export_status": str(report.get("status", "") or ""),
        "tdx_day_input_dir": str(report.get("input_dir", "") or ""),
        "tdx_day_symbol_count": str(report.get("symbol_count", "") or ""),
        "tdx_day_row_count": str(report.get("row_count", "") or ""),
        "tdx_day_start": str(report.get("start", "") or ""),
        "tdx_day_end": str(report.get("end", "") or ""),
    }


def _tdx_metadata_checks(
    label: str,
    payload: dict[str, Any],
    *,
    report_hash: str,
    expected: dict[str, str],
) -> list[str]:
    checks = []
    if not str(payload.get("tdx_day_export_sha256", "") or "").strip():
        checks.append(f"{label} has no tdx_day_export_sha256.")
    elif report_hash and str(payload.get("tdx_day_export_sha256")) != report_hash:
        checks.append(f"{label} tdx_day_export_sha256 does not match tdx_day_export.json.")
    if not str(payload.get("tdx_day_export_report", "") or "").strip():
        checks.append(f"{label} has no tdx_day_export_report.")
    for key, expected_value in expected.items():
        if not expected_value:
            continue
        actual = str(payload.get(key, "") or "")
        if actual != expected_value:
            checks.append(f"{label} {key} does not match tdx_day_export.json.")
    return checks


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_metadata(cfg) -> dict[str, str] | None:
    if cfg is None:
        return None
    try:
        cache = Path(str(cfg.data.cache_path))
    except AttributeError:
        return None
    if not cache.exists():
        return None
    return BarStorage(cache).load_metadata()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _dict_payload(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
