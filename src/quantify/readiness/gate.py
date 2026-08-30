"""Micro-live readiness gate.

The gate creates manual preparation artifacts only. It never creates broker
orders and never connects to live trading infrastructure.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from quantify.data.cache_metadata import cache_metadata_blockers
from quantify.research.evidence_validation import (
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

ReadinessDecision = Literal["PASS", "WATCH", "BLOCK"]

_BLOCKING_TARGET_FLAGS = {"ST", "DELISTED", "SUSPENDED", "LIMIT_UP", "LIMIT_DOWN", "MISSING_PRICE"}
_WATCH_TARGET_FLAGS = {"LOW_LIQUIDITY", "HIGH_PARTICIPATION", "HIGH_WEIGHT"}
_MANUAL_ONLY_INSTRUCTION = "MANUAL_REFERENCE_ONLY_NO_BROKER_ORDER"
_FORBIDDEN_MANUAL_SHEET_TOKENS = {
    "AUTO_ORDER",
    "BROKER",
    "BROKER_ORDER",
    "LIVE",
    "LIVE_ORDER",
    "ORDER_SUBMIT",
    "SUBMIT_ORDER",
}
_APPROVAL_REQUIRED_ARTIFACTS = {
    "real_data_bootstrap.json",
    "real_data_gate.json",
    "data_coverage.json",
    "market_context_readiness.json",
    "llm_review.json",
    "data_audit.json",
    "robustness_report.json",
    "walk_forward_report.json",
    "candidate_walk_forward_report.json",
    "candidate_regime_validation_report.json",
    "candidate_selection.json",
    "selection_evidence_manifest.json",
    "benchmark_report.json",
    "multiple_testing_report.json",
    "trial_registry_review.json",
    "candidate_experiment_completion.json",
    "paper_state.json",
    "paper_daily_review.json",
    "paper_stability.json",
    "target_portfolio.csv",
    "target_portfolio.json",
    "manual_trade_sheet.csv",
    "risk_budget.json",
    "run_manifest.json",
    "promotion_metadata_check.json",
}
_TARGET_ROW_FIELDS = (
    "symbol",
    "industry",
    "target_weight",
    "score",
    "latest_price",
    "avg_amount_20d",
    "estimated_participation_rate",
    "target_value",
    "target_quantity",
    "estimated_cost",
    "current_quantity",
    "quantity_delta",
    "instruction",
    "reason",
    "risk_flags",
)
_TARGET_NUMERIC_FIELDS = {
    "target_weight",
    "score",
    "latest_price",
    "avg_amount_20d",
    "estimated_participation_rate",
    "target_value",
    "target_quantity",
    "estimated_cost",
    "current_quantity",
    "quantity_delta",
}
_TARGET_INTEGER_FIELDS = {"target_quantity", "current_quantity", "quantity_delta"}
_MANUAL_CORE_FIELDS = (
    "symbol",
    "target_quantity",
    "quantity_delta",
    "latest_price",
    "estimated_cost",
)


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    approval_required: bool
    approved_by: str
    approved_at: str
    approval_notes: str
    allowed_stage: str
    evidence_snapshot: dict[str, str]

    def to_dict(self) -> dict[str, str | bool | dict[str, str]]:
        return {
            "approval_required": self.approval_required,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "approval_notes": self.approval_notes,
            "allowed_stage": self.allowed_stage,
            "evidence_snapshot": self.evidence_snapshot,
        }


@dataclass(frozen=True, slots=True)
class ReadinessFinding:
    severity: ReadinessDecision
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    decision: ReadinessDecision
    findings: list[ReadinessFinding]
    risk_budget: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "findings": [finding.to_dict() for finding in self.findings],
            "risk_budget": self.risk_budget,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Micro-live Readiness: {self.decision}",
            "",
            "## Findings",
        ]
        lines.extend(
            f"- `{finding.severity}` `{finding.code}`: {finding.message}"
            for finding in self.findings
        )
        if not self.findings:
            lines.append("- No readiness findings.")
        lines.extend(["", "## Risk Budget"])
        lines.extend(f"- {key}: `{value}`" for key, value in self.risk_budget.items())
        lines.extend(
            [
                "",
                "## Manual Boundary",
                "- This gate only prepares a manual reference sheet.",
                "- It does not submit, route, or authorize real broker orders.",
            ]
        )
        return "\n".join(lines) + "\n"


def write_approval_record(
    report_dir: str | Path,
    *,
    approved_by: str,
    allowed_stage: str = "micro_live_ready",
    approval_notes: str = "",
    approval_required: bool = True,
) -> Path:
    root = Path(report_dir)
    root.mkdir(parents=True, exist_ok=True)
    _prepare_review_materials(root, overwrite=True)
    record = ApprovalRecord(
        approval_required=approval_required,
        approved_by=approved_by,
        approved_at=datetime.now(UTC).isoformat(),
        approval_notes=approval_notes,
        allowed_stage=allowed_stage,
        evidence_snapshot=_approval_evidence_snapshot(root),
    )
    path = root / "approval_record.json"
    path.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def evaluate_micro_live_readiness(report_dir: str | Path) -> ReadinessResult:
    root = Path(report_dir)
    real_data_bootstrap = _read_json(root / "real_data_bootstrap.json")
    real_data_gate = _read_json(root / "real_data_gate.json")
    data_coverage = _read_json(root / "data_coverage.json")
    market_context_readiness = _read_json(root / "market_context_readiness.json")
    llm_review = _read_json(root / "llm_review.json")
    data_audit = _read_json(root / "data_audit.json")
    robustness = _read_json(root / "robustness_report.json")
    walk_forward = _read_json(root / "walk_forward_report.json")
    candidate_walk_forward = _read_json(root / "candidate_walk_forward_report.json")
    candidate_regime_validation = _read_json(root / "candidate_regime_validation_report.json")
    candidate_selection = _read_json(root / "candidate_selection.json")
    selection_evidence = _read_json(root / "selection_evidence_manifest.json")
    benchmark_report = _read_json(root / "benchmark_report.json")
    multiple_testing_report = _read_json(root / "multiple_testing_report.json")
    trial_registry_review = _read_json(root / "trial_registry_review.json")
    candidate_completion = _read_json(root / "candidate_experiment_completion.json")
    paper_state = _read_json(root / "paper_state.json")
    paper_daily_review = _read_json(root / "paper_daily_review.json")
    paper_stability = _read_json(root / "paper_stability.json")
    target_plan = _read_json(root / "target_portfolio.json")
    run_manifest = _read_json(root / "run_manifest.json")
    promotion_metadata = _read_json(root / "promotion_metadata_check.json")
    approval = _read_json(root / "approval_record.json")
    findings: list[ReadinessFinding] = []

    _merge_status_finding(
        findings,
        real_data_bootstrap,
        "REAL_DATA_BOOTSTRAP",
        missing="real_data_bootstrap.json is required before micro-live readiness.",
        status_key="decision",
        missing_severity="BLOCK",
    )
    _merge_status_finding(
        findings,
        real_data_gate,
        "REAL_DATA_GATE",
        missing="real_data_gate.json is required before micro-live readiness.",
        status_key="decision",
        missing_severity="BLOCK",
    )
    _merge_status_finding(
        findings,
        data_coverage,
        "DATA_COVERAGE",
        missing="data_coverage.json is required before micro-live readiness.",
        missing_severity="BLOCK",
    )
    _merge_status_finding(
        findings,
        market_context_readiness,
        "MARKET_CONTEXT_READINESS",
        missing="market_context_readiness.json is required before micro-live readiness.",
        status_key="decision",
        missing_severity="BLOCK",
    )
    _merge_status_finding(
        findings,
        promotion_metadata,
        "PROMOTION_METADATA",
        missing="promotion_metadata_check.json is required before micro-live readiness.",
        missing_severity="BLOCK",
    )

    if not llm_review:
        findings.append(
            ReadinessFinding("BLOCK", "MISSING_LLM_REVIEW", "llm_review.json is required.")
        )
    else:
        llm_decision = str(llm_review.get("decision", "")).upper()
        if llm_decision == "BLOCK":
            findings.append(
                ReadinessFinding(
                    "BLOCK", "LLM_REVIEW_BLOCK", "The deterministic LLM review is BLOCK."
                )
            )
        elif llm_decision == "WATCH":
            findings.append(
                ReadinessFinding(
                    "WATCH", "LLM_REVIEW_WATCH", "The deterministic LLM review is WATCH."
                )
            )
        elif llm_decision != "PASS":
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    "UNKNOWN_LLM_REVIEW",
                    "llm_review.json decision is missing or unknown.",
                )
            )

    assumptions = _review_assumptions(llm_review)
    risk_budget = _risk_budget(assumptions)
    if assumptions.get("demo_data_used"):
        findings.append(
            ReadinessFinding("BLOCK", "DEMO_DATA", "Demo data cannot support micro-live readiness.")
        )

    _merge_status_finding(
        findings,
        data_audit,
        "DATA_AUDIT",
        missing="data_audit.json is required before micro-live readiness.",
        missing_severity="BLOCK",
    )
    _merge_status_finding(
        findings,
        robustness,
        "ROBUSTNESS",
        missing="robustness_report.json is required before micro-live readiness.",
        missing_severity="BLOCK",
    )
    if robustness:
        robustness_validation = validate_robustness_selection_safe_payload(robustness)
        if not robustness_validation.safe:
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    "ROBUSTNESS_SELECTION_UNSAFE",
                    "robustness_report.json is diagnostic-only or fails the selection-safe "
                    "robustness contract: "
                    + "; ".join(robustness_validation.reasons),
                )
            )
    _merge_status_finding(
        findings,
        walk_forward,
        "WALK_FORWARD",
        missing="walk_forward_report.json is required before micro-live readiness.",
        missing_severity="BLOCK",
    )
    _merge_status_finding(
        findings,
        candidate_walk_forward,
        "CANDIDATE_WALK_FORWARD",
        missing="candidate_walk_forward_report.json is required before micro-live readiness.",
        missing_severity="BLOCK",
    )
    findings.extend(
        _selection_safety_findings(
            walk_forward=walk_forward,
            candidate_walk_forward=candidate_walk_forward,
        )
    )
    _merge_status_finding(
        findings,
        candidate_regime_validation,
        "CANDIDATE_REGIME_VALIDATION",
        missing="candidate_regime_validation_report.json is required before micro-live readiness.",
        missing_severity="BLOCK",
    )
    _merge_status_finding(
        findings,
        candidate_selection,
        "CANDIDATE_SELECTION",
        missing="candidate_selection.json is required before micro-live readiness.",
        missing_severity="BLOCK",
    )
    _merge_status_finding(
        findings,
        selection_evidence,
        "SELECTION_EVIDENCE_MANIFEST",
        missing="selection_evidence_manifest.json is required before micro-live readiness.",
        missing_severity="BLOCK",
    )
    if selection_evidence:
        current_selection_evidence = build_selection_evidence_manifest(root)
        if (
            current_selection_evidence.status == "BLOCK"
            or selection_evidence.get("artifact_set_sha256")
            != current_selection_evidence.artifact_set_sha256
        ):
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    "SELECTION_EVIDENCE_MANIFEST_MISMATCH",
                    "Selection evidence hashes or current artifact contracts do not match the "
                    "recorded manifest.",
                )
            )
    findings.extend(
        _statistical_evidence_findings(
            root=root,
            candidate_selection=candidate_selection,
            run_manifest=run_manifest,
            benchmark_report=benchmark_report,
            multiple_testing_report=multiple_testing_report,
            trial_registry_review=trial_registry_review,
        )
    )
    _merge_status_finding(
        findings,
        candidate_completion,
        "CANDIDATE_EXPERIMENT_COMPLETION",
        missing="candidate_experiment_completion.json is required before micro-live readiness.",
        status_key="decision",
        missing_severity="BLOCK",
    )
    findings.extend(
        _candidate_identity_findings(
            candidate_selection=candidate_selection,
            candidate_completion=candidate_completion,
            candidate_walk_forward=candidate_walk_forward,
            candidate_regime_validation=candidate_regime_validation,
            paper_state=paper_state,
            target_plan=target_plan,
        )
    )
    findings.extend(_run_manifest_findings(run_manifest))
    findings.extend(_promotion_attestation_findings(promotion_metadata, run_manifest))
    findings.extend(_paper_data_identity_findings(run_manifest, paper_state))

    observed_days = int((paper_state or {}).get("observed_days", 0))
    if not paper_state:
        findings.append(
            ReadinessFinding("BLOCK", "MISSING_PAPER_STATE", "paper_state.json is required.")
        )
    elif observed_days < 20:
        findings.append(
            ReadinessFinding(
                "WATCH",
                "SHORT_PAPER_RUN",
                "Paper run is shorter than 20 observed trading days.",
            )
        )
    if (paper_state or {}).get("broker_connection") not in {None, "", "none"}:
        findings.append(
            ReadinessFinding(
                "BLOCK", "BROKER_CONNECTED", "Paper artifacts must not connect to a broker."
            )
        )

    _merge_status_finding(
        findings,
        paper_daily_review,
        "PAPER_DAILY_REVIEW",
        missing="paper_daily_review.json is required before micro-live readiness.",
        missing_severity="BLOCK",
    )
    _merge_status_finding(
        findings,
        paper_stability,
        "PAPER_STABILITY",
        missing="paper_stability.json is required before micro-live readiness.",
        missing_severity="BLOCK",
    )
    findings.extend(_target_plan_findings(root, risk_budget=risk_budget))
    findings.extend(_manual_trade_sheet_findings(root))
    findings.extend(_risk_budget_findings(root, risk_budget))

    if not approval:
        findings.append(
            ReadinessFinding("BLOCK", "MISSING_APPROVAL", "approval_record.json is required.")
        )
    elif (
        approval.get("approval_required") is not True
        or approval.get("allowed_stage") != "micro_live_ready"
        or not approval.get("approved_by")
        or not approval.get("approved_at")
        or not str(approval.get("approval_notes", "")).strip()
    ):
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "INVALID_APPROVAL",
                "Approval must be required, name an approver, include notes, and allow micro_live_ready.",
            )
        )
    else:
        findings.extend(
            ReadinessFinding("BLOCK", code, message)
            for code, message in approval_snapshot_blockers(root, approval)
        )

    return ReadinessResult(
        decision=_combine_decision([finding.severity for finding in findings]),
        findings=findings,
        risk_budget=risk_budget,
    )


def write_readiness_outputs(report_dir: str | Path) -> Path:
    root = Path(report_dir)
    root.mkdir(parents=True, exist_ok=True)
    _prepare_review_materials(root, overwrite=False)
    result = evaluate_micro_live_readiness(root)
    (root / "micro_live_readiness.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "micro_live_readiness.md").write_text(result.to_markdown(), encoding="utf-8")
    return root


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def approval_snapshot_blockers(root: str | Path, approval: dict[str, Any]) -> list[tuple[str, str]]:
    root = Path(root)
    expected = approval.get("evidence_snapshot", {})
    if not isinstance(expected, dict) or not expected:
        return [
            (
                "APPROVAL_SNAPSHOT_MISSING",
                "Approval record must include evidence fingerprints for the current report.",
            )
        ]
    missing_required = sorted(_APPROVAL_REQUIRED_ARTIFACTS - set(expected))
    if missing_required:
        return [
            (
                "APPROVAL_SNAPSHOT_INCOMPLETE",
                "Approval evidence snapshot is missing required artifacts: "
                f"{', '.join(missing_required)}.",
            )
        ]
    current = _approval_evidence_snapshot(root)
    missing = [name for name, digest in expected.items() if digest and current.get(name) != digest]
    if missing:
        return [
            (
                "APPROVAL_SNAPSHOT_MISMATCH",
                "Approval evidence snapshot no longer matches current artifacts: "
                f"{', '.join(sorted(missing))}.",
            )
        ]
    return []


def _approval_evidence_snapshot(root: Path) -> dict[str, str]:
    artifacts = [
        "real_data_bootstrap.json",
        "real_data_gate.json",
        "data_coverage.json",
        "market_context_readiness.json",
        "llm_review.json",
        "data_audit.json",
        "robustness_report.json",
        "walk_forward_report.json",
        "candidate_walk_forward_report.json",
        "candidate_regime_validation_report.json",
        "candidate_selection.json",
        "selection_evidence_manifest.json",
        "benchmark_report.json",
        "multiple_testing_report.json",
        "trial_registry_review.json",
        "candidate_experiment_completion.json",
        "paper_state.json",
        "paper_daily_review.json",
        "paper_stability.json",
        "target_portfolio.csv",
        "target_portfolio.json",
        "manual_trade_sheet.csv",
        "risk_budget.json",
        "run_manifest.json",
        "promotion_metadata_check.json",
    ]
    return {
        artifact: _file_sha256(root / artifact)
        for artifact in artifacts
        if (root / artifact).exists()
    }


def _statistical_evidence_findings(
    *,
    root: Path,
    candidate_selection: dict[str, Any],
    run_manifest: dict[str, Any],
    benchmark_report: dict[str, Any],
    multiple_testing_report: dict[str, Any],
    trial_registry_review: dict[str, Any],
) -> list[ReadinessFinding]:
    candidate = str(candidate_selection.get("selected_candidate") or "").strip()
    research_parameters = run_manifest.get("research_parameters", {})
    expected_symbol = (
        str(research_parameters.get("index_code") or "").strip()
        if isinstance(research_parameters, dict)
        else ""
    )
    validations = (
        (
            "BENCHMARK_REPORT",
            "benchmark_report.json",
            benchmark_report,
            lambda: validate_benchmark_payload(
                benchmark_report,
                expected_symbol=expected_symbol,
            ),
        ),
        (
            "MULTIPLE_TESTING_REPORT",
            "multiple_testing_report.json",
            multiple_testing_report,
            lambda: validate_multiple_testing_payload(
                multiple_testing_report,
                expected_candidate=candidate,
            ),
        ),
        (
            "TRIAL_REGISTRY_REVIEW",
            "trial_registry_review.json",
            trial_registry_review,
            lambda: validate_trial_registry_review_payload(
                trial_registry_review,
                expected_candidate=candidate,
                report_dir=root,
            ),
        ),
    )
    findings: list[ReadinessFinding] = []
    for code, filename, payload, validate in validations:
        path = root / filename
        if not path.is_file():
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    f"MISSING_{code}",
                    f"{filename} is required before micro-live readiness.",
                )
            )
            continue
        validation = validate()
        if not payload or not validation.valid:
            detail = "; ".join(validation.reasons) or "the JSON payload is empty or unreadable"
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    f"{code}_CONTRACT_INVALID",
                    f"{filename} fails its retained-evidence contract: {detail}",
                )
            )
            continue
        if validation.status != "PASS":
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    f"{code}_STATUS_NOT_PASS",
                    f"{filename} status is {validation.status}; PASS is required for "
                    "micro-live readiness.",
                )
            )
    return findings


def _run_manifest_findings(manifest: dict[str, Any]) -> list[ReadinessFinding]:
    if not manifest:
        return [
            ReadinessFinding(
                "BLOCK",
                "MISSING_RUN_MANIFEST",
                "run_manifest.json is required before micro-live readiness.",
            )
        ]
    findings: list[ReadinessFinding] = []
    if not str(manifest.get("cache_sha256") or "").strip():
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "RUN_MANIFEST_CACHE_SHA256_MISSING",
                "run_manifest.json must record cache_sha256 before micro-live readiness.",
            )
        )
    if manifest.get("demo_data_used") is True:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "RUN_MANIFEST_DEMO_DATA",
                "run_manifest.json says demo data was used.",
            )
        )
    if not str(manifest.get("in_sample_end", "") or "").strip():
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "RUN_MANIFEST_MISSING_IN_SAMPLE_END",
                "run_manifest.json must record in_sample_end before micro-live readiness.",
            )
        )
    if not str(manifest.get("out_sample_start", "") or "").strip():
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "RUN_MANIFEST_MISSING_OUT_SAMPLE_START",
                "run_manifest.json must record out_sample_start before micro-live readiness.",
            )
        )
    data_version = manifest.get("data_version", {})
    if not isinstance(data_version, dict):
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "RUN_MANIFEST_INVALID_DATA_VERSION",
                "run_manifest.json data_version must be an object with source QA provenance.",
            )
        )
        return findings
    metadata = dict(data_version)
    metadata["data_source_qa_require_evidence_manifest"] = "true"
    findings.extend(
        ReadinessFinding(
            "BLOCK",
            "RUN_MANIFEST_PROMOTION_METADATA_BLOCK",
            blocker,
        )
        for blocker in cache_metadata_blockers(metadata)
    )
    required_attestation = {
        "cache_logical_bar_fingerprint": "RUN_MANIFEST_LOGICAL_BAR_FINGERPRINT_MISSING",
        "cache_latest_import_batch_id": "RUN_MANIFEST_IMPORT_BATCH_MISSING",
    }
    for key, code in required_attestation.items():
        if not str(metadata.get(key, "") or "").strip():
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    code,
                    f"run_manifest.json data_version must record {key}.",
                )
            )
    if (
        str(metadata.get("cache_logical_bar_fingerprint_algorithm", "") or "")
        != "sha256:quantify.logical-bars.v1"
    ):
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "RUN_MANIFEST_LOGICAL_BAR_ALGORITHM_INVALID",
                "run_manifest.json has a missing or unsupported logical bar fingerprint algorithm.",
            )
        )
    if str(metadata.get("cache_lineage_schema_version", "") or "") != "1":
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "RUN_MANIFEST_LINEAGE_SCHEMA_INVALID",
                "run_manifest.json must record cache_lineage_schema_version=1.",
            )
        )
    return findings


def _promotion_attestation_findings(
    promotion: dict[str, Any],
    manifest: dict[str, Any],
) -> list[ReadinessFinding]:
    if not promotion or not manifest:
        return []
    findings: list[ReadinessFinding] = []
    metadata = promotion.get("metadata", {})
    stats = promotion.get("cache_stats", {})
    version = manifest.get("data_version", {})
    if not isinstance(metadata, dict):
        metadata = {}
    if not isinstance(stats, dict):
        stats = {}
    if not isinstance(version, dict):
        version = {}

    if str(promotion.get("cache_path") or "") != str(manifest.get("cache_path") or ""):
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "PROMOTION_CACHE_PATH_MISMATCH",
                "promotion metadata cache path does not match run_manifest.json.",
            )
        )
    manifest_fingerprint = str(version.get("cache_logical_bar_fingerprint") or "")
    claimed_fingerprint = str(metadata.get("cache_logical_bar_fingerprint") or "")
    actual_fingerprint = str(stats.get("logical_bar_fingerprint_actual") or "")
    if (
        not manifest_fingerprint
        or manifest_fingerprint != claimed_fingerprint
        or manifest_fingerprint != actual_fingerprint
    ):
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "PROMOTION_LOGICAL_BAR_IDENTITY_MISMATCH",
                "promotion metadata claimed/actual logical bar identity does not match the run manifest.",
            )
        )
    manifest_batch = str(version.get("cache_latest_import_batch_id") or "")
    promotion_batch = str(stats.get("latest_import_batch_id") or "")
    if not manifest_batch or manifest_batch != promotion_batch:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "PROMOTION_IMPORT_BATCH_MISMATCH",
                "promotion metadata import batch does not match the run manifest.",
            )
        )
    bar_count = int(stats.get("bar_count", 0) or 0)
    lineage_count = int(stats.get("provenance_current_lineage_count", 0) or 0)
    mismatches = int(stats.get("provenance_mismatched_current_lineage_count", 0) or 0)
    if bar_count <= 0 or lineage_count != bar_count or mismatches:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "PROMOTION_LINEAGE_INCOMPLETE",
                "promotion metadata does not prove complete matching lineage for current bars.",
            )
        )
    return findings


def _paper_data_identity_findings(
    manifest: dict[str, Any],
    paper_state: dict[str, Any],
) -> list[ReadinessFinding]:
    if not manifest or not paper_state:
        return []
    run_context = paper_state.get("run_context")
    if not isinstance(run_context, dict) or not run_context:
        return [
            ReadinessFinding(
                "BLOCK",
                "PAPER_RUN_CONTEXT_MISSING",
                "paper_state.json must lock the data, strategy, and broker run context.",
            )
        ]
    paper_data = run_context.get("data", {})
    if not isinstance(paper_data, dict):
        paper_data = {}
    manifest_version = manifest.get("data_version", {})
    if not isinstance(manifest_version, dict):
        manifest_version = {}
    expected_hash = str(manifest.get("cache_sha256") or "").strip()
    paper_hash = str(paper_data.get("cache_sha256") or "").strip()
    expected_source_fingerprint = str(
        manifest_version.get("csv_dataset_fingerprint")
        or manifest_version.get("raw_vendor_bars_sha256")
        or ""
    ).strip()
    paper_source_fingerprint = str(paper_data.get("dataset_fingerprint") or "").strip()
    expected_logical_fingerprint = str(
        manifest_version.get("cache_logical_bar_fingerprint") or ""
    ).strip()
    paper_logical_fingerprint = str(
        paper_data.get("logical_bar_fingerprint") or ""
    ).strip()
    expected_batch = str(manifest_version.get("cache_latest_import_batch_id") or "").strip()
    paper_batch = str(paper_data.get("import_batch_id") or "").strip()
    findings: list[ReadinessFinding] = []
    if not paper_hash or paper_hash != expected_hash:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "PAPER_CACHE_IDENTITY_MISMATCH",
                "paper_state.json cache_sha256 does not match the research run manifest.",
            )
        )
    if not paper_logical_fingerprint or paper_logical_fingerprint != expected_logical_fingerprint:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "PAPER_DATASET_IDENTITY_MISMATCH",
                "paper_state.json logical bar fingerprint does not match the research run manifest.",
            )
        )
    if not paper_batch or paper_batch != expected_batch:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "PAPER_IMPORT_BATCH_MISMATCH",
                "paper_state.json import batch does not match the research run manifest.",
            )
        )
    if expected_source_fingerprint and paper_source_fingerprint != expected_source_fingerprint:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "PAPER_SOURCE_DATASET_IDENTITY_MISMATCH",
                "paper_state.json source dataset fingerprint does not match the research run manifest.",
            )
        )
    return findings


def _candidate_identity_findings(
    *,
    candidate_selection: dict[str, Any],
    candidate_completion: dict[str, Any],
    candidate_walk_forward: dict[str, Any],
    candidate_regime_validation: dict[str, Any],
    paper_state: dict[str, Any],
    target_plan: dict[str, Any],
) -> list[ReadinessFinding]:
    findings: list[ReadinessFinding] = []
    selected = str(candidate_selection.get("selected_candidate") or "").strip()
    if not selected:
        return [
            ReadinessFinding(
                "BLOCK",
                "MISSING_SELECTED_CANDIDATE",
                "candidate_selection.json must name the selected candidate.",
            )
        ]

    selected_results = [
        item
        for item in candidate_selection.get("results", []) or []
        if isinstance(item, dict) and str(item.get("name") or "").strip() == selected
    ]
    if not selected_results:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "SELECTED_CANDIDATE_RESULT_MISSING",
                f"candidate_selection.json has no result row for {selected}.",
            )
        )
    else:
        score = selected_results[0].get("score", {})
        score = score if isinstance(score, dict) else {}
        if str(score.get("decision") or "").upper() != "PASS":
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    "SELECTED_CANDIDATE_NOT_PASS",
                    f"Selected candidate {selected} does not have a PASS score decision.",
                )
            )

    completion_candidate = str(candidate_completion.get("selected_candidate") or "").strip()
    if completion_candidate != selected:
        findings.append(
            _candidate_mismatch(
                "candidate_experiment_completion.json", selected, completion_candidate
            )
        )
    if not str(candidate_completion.get("run_id") or "").strip():
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "CANDIDATE_COMPLETION_RUN_ID_MISSING",
                "candidate_experiment_completion.json must record a non-empty run_id.",
            )
        )
    if str(candidate_completion.get("launch_decision") or "").upper() != "PASS":
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "CANDIDATE_COMPLETION_LAUNCH_NOT_PASS",
                "Candidate completion must be tied to a PASS launch contract.",
            )
        )
    completion_artifacts = candidate_completion.get("artifacts", [])
    if not isinstance(completion_artifacts, list) or not completion_artifacts:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "CANDIDATE_COMPLETION_ARTIFACTS_MISSING",
                "Candidate completion must include its reviewed artifact contract.",
            )
        )
    elif any(
        not isinstance(item, dict) or str(item.get("status") or "").upper() != "PASS"
        for item in completion_artifacts
    ):
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "CANDIDATE_COMPLETION_ARTIFACT_NOT_PASS",
                "Every artifact in the candidate completion contract must be PASS.",
            )
        )

    for filename, payload in (
        ("candidate_walk_forward_report.json", candidate_walk_forward),
        ("candidate_regime_validation_report.json", candidate_regime_validation),
    ):
        if payload and not _artifact_contains_candidate(payload, selected):
            findings.append(_candidate_mismatch(filename, selected, "missing"))

    paper_candidate = str(paper_state.get("candidate") or "").strip()
    if paper_candidate != selected:
        findings.append(_candidate_mismatch("paper_state.json", selected, paper_candidate))

    target_candidate = str(target_plan.get("candidate") or "").strip()
    if target_candidate != selected:
        findings.append(_candidate_mismatch("target_portfolio.json", selected, target_candidate))
    return findings


def _artifact_contains_candidate(payload: dict[str, Any], selected: str) -> bool:
    candidates = {
        str(payload.get(key) or "").strip()
        for key in ("selected_candidate", "best_candidate", "top_candidate")
        if payload.get(key)
    }
    for collection in ("results", "summaries", "buckets", "windows"):
        for item in payload.get(collection, []) or []:
            if not isinstance(item, dict):
                continue
            candidate = str(item.get("candidate") or item.get("name") or "").strip()
            if candidate:
                candidates.add(candidate)
    return selected in candidates


def _candidate_mismatch(filename: str, expected: str, actual: str) -> ReadinessFinding:
    return ReadinessFinding(
        "BLOCK",
        "CANDIDATE_EVIDENCE_IDENTITY_MISMATCH",
        f"{filename} candidate {actual or 'missing'} does not match selected candidate {expected}.",
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _merge_status_finding(
    findings: list[ReadinessFinding],
    artifact: dict[str, Any],
    prefix: str,
    *,
    missing: str,
    status_key: str = "status",
    missing_severity: ReadinessDecision = "WATCH",
) -> None:
    if not artifact:
        findings.append(ReadinessFinding(missing_severity, f"MISSING_{prefix}", missing))
        return
    status = str(artifact.get(status_key, "")).upper()
    if status == "BLOCK":
        findings.append(ReadinessFinding("BLOCK", f"{prefix}_BLOCK", f"{prefix.lower()} is BLOCK."))
    elif status == "WATCH":
        findings.append(ReadinessFinding("WATCH", f"{prefix}_WATCH", f"{prefix.lower()} is WATCH."))
    elif status != "PASS":
        findings.append(
            ReadinessFinding(
                missing_severity,
                f"UNKNOWN_{prefix}",
                f"{prefix.lower()} status is missing or unknown.",
            )
        )


def _selection_safety_findings(
    *,
    walk_forward: dict[str, Any],
    candidate_walk_forward: dict[str, Any],
) -> list[ReadinessFinding]:
    findings: list[ReadinessFinding] = []
    for payload, code, filename, artifact_type in (
        (
            walk_forward,
            "WALK_FORWARD_SELECTION_UNSAFE",
            "walk_forward_report.json",
            WALK_FORWARD_ARTIFACT,
        ),
        (
            candidate_walk_forward,
            "CANDIDATE_WALK_FORWARD_SELECTION_UNSAFE",
            "candidate_walk_forward_report.json",
            CANDIDATE_WALK_FORWARD_ARTIFACT,
        ),
    ):
        validation = validate_selection_safe_payload(payload, artifact_type=artifact_type)
        if payload and not validation.safe:
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    code,
                    f"{filename} does not satisfy the selection-safe v2 contract: "
                    + "; ".join(validation.reasons),
                )
            )
    return findings


def _target_plan_findings(
    root: Path,
    *,
    risk_budget: dict[str, Any],
) -> list[ReadinessFinding]:
    csv_path = root / "target_portfolio.csv"
    json_path = root / "target_portfolio.json"
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return [
            ReadinessFinding(
                "BLOCK",
                "MISSING_TARGET_PORTFOLIO",
                "target_portfolio.csv is required before micro-live readiness.",
            )
        ]

    frame, csv_error = _read_csv(csv_path)
    if frame is None:
        return [
            ReadinessFinding(
                "BLOCK",
                "INVALID_TARGET_PORTFOLIO",
                f"target_portfolio.csv could not be read: {csv_error}",
            )
        ]

    findings: list[ReadinessFinding] = []
    target_plan, json_error = _read_json_object(json_path)
    if target_plan is None:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "INVALID_TARGET_PORTFOLIO_JSON",
                f"target_portfolio.json is required and must contain an object: {json_error}",
            )
        )
        target_plan = {}

    missing_csv_fields = sorted(set(_TARGET_ROW_FIELDS) - set(frame.columns))
    json_rows = target_plan.get("rows")
    if not isinstance(json_rows, list) or any(not isinstance(row, dict) for row in json_rows):
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "INVALID_TARGET_PORTFOLIO_JSON_ROWS",
                "target_portfolio.json rows must be a list of row objects.",
            )
        )
        json_rows = []
    missing_json_fields = sorted(
        {field for row in json_rows for field in _TARGET_ROW_FIELDS if field not in row}
    )
    if missing_csv_fields or missing_json_fields:
        details = []
        if missing_csv_fields:
            details.append(f"CSV missing {', '.join(missing_csv_fields)}")
        if missing_json_fields:
            details.append(f"JSON rows missing {', '.join(missing_json_fields)}")
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "TARGET_PORTFOLIO_SCHEMA_MISMATCH",
                "Target CSV/JSON row schema is incomplete: " + "; ".join(details) + ".",
            )
        )

    candidate = str(target_plan.get("candidate") or "").strip()
    if not candidate:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "TARGET_PORTFOLIO_CANDIDATE_MISSING",
                "target_portfolio.json must name the candidate used to create the rows.",
            )
        )
    if "candidate" in frame and any(
        str(value).strip() != candidate for value in frame["candidate"].tolist()
    ):
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "TARGET_PORTFOLIO_CANDIDATE_MISMATCH",
                "target_portfolio.csv candidate values do not match target_portfolio.json.",
            )
        )

    records = frame.to_dict("records")
    if len(records) != len(json_rows):
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "TARGET_PORTFOLIO_ROW_MISMATCH",
                "target_portfolio.csv and target_portfolio.json must contain the same number of rows.",
            )
        )
    elif not missing_csv_fields and not missing_json_fields:
        mismatch = _first_row_mismatch(records, json_rows, _TARGET_ROW_FIELDS)
        if mismatch:
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    "TARGET_PORTFOLIO_ROW_MISMATCH",
                    f"target_portfolio.csv and target_portfolio.json differ: {mismatch}.",
                )
            )

    plan_values, plan_findings = _target_plan_values(target_plan, len(json_rows))
    findings.extend(plan_findings)
    if not missing_csv_fields and plan_values is not None:
        findings.extend(
            _target_row_findings(
                records,
                capital=plan_values["capital"],
                cash_buffer_pct=plan_values["cash_buffer_pct"],
                lot_size=int(plan_values["lot_size"]),
                max_position_pct=float(risk_budget["max_position_pct"]),
                target_plan=target_plan,
            )
        )

    if "risk_flags" not in frame:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "MISSING_TARGET_RISK_FLAGS",
                "target_portfolio.csv must include risk_flags evidence.",
            )
        )
    else:
        blocking_rows = _rows_with_flags(frame, _BLOCKING_TARGET_FLAGS)
        watch_rows = _rows_with_flags(frame, _WATCH_TARGET_FLAGS)
        if blocking_rows:
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    "TARGET_EXECUTION_RISK_FLAGS",
                    "Target portfolio contains blocking execution risk flags: "
                    f"{_format_flag_examples(blocking_rows)}.",
                )
            )
        if watch_rows:
            findings.append(
                ReadinessFinding(
                    "WATCH",
                    "TARGET_WATCH_RISK_FLAGS",
                    "Target portfolio contains liquidity, participation, or concentration watch flags: "
                    f"{_format_flag_examples(watch_rows)}.",
                )
            )
    if frame.empty:
        findings.append(
            ReadinessFinding(
                "WATCH",
                "EMPTY_TARGET_PORTFOLIO",
                "target_portfolio.csv has no target rows; confirm whether the strategy intentionally holds cash.",
            )
        )
    return findings


def _manual_trade_sheet_findings(root: Path) -> list[ReadinessFinding]:
    path = root / "manual_trade_sheet.csv"
    if not path.exists() or path.stat().st_size == 0:
        return [
            ReadinessFinding(
                "BLOCK",
                "MISSING_MANUAL_TRADE_SHEET",
                "manual_trade_sheet.csv is required as a manual-only reference artifact.",
            )
        ]
    frame, error = _read_csv(path)
    if frame is None:
        return [
            ReadinessFinding(
                "BLOCK",
                "INVALID_MANUAL_TRADE_SHEET",
                f"manual_trade_sheet.csv could not be read: {error}",
            )
        ]
    findings: list[ReadinessFinding] = []
    missing = sorted((set(_MANUAL_CORE_FIELDS) | {"instruction"}) - set(frame.columns))
    if missing:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "MANUAL_TRADE_SHEET_SCHEMA_MISMATCH",
                f"manual_trade_sheet.csv is missing required fields: {', '.join(missing)}.",
            )
        )

    if "instruction" in frame:
        instructions = [str(value).strip().upper() for value in frame["instruction"].tolist()]
        forbidden = {
            instruction for instruction in instructions if instruction != _MANUAL_ONLY_INSTRUCTION
        }
        if forbidden:
            forbidden_with_tokens = {
                instruction
                for instruction in forbidden
                if any(token in instruction for token in _FORBIDDEN_MANUAL_SHEET_TOKENS)
            }
            examples = ", ".join(sorted(forbidden_with_tokens or forbidden)[:5]) or "blank"
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    "MANUAL_TRADE_SHEET_NOT_MANUAL_ONLY",
                    "manual_trade_sheet.csv must only contain "
                    f"{_MANUAL_ONLY_INSTRUCTION}; found {examples}.",
                )
            )

    target, target_error = _read_csv(root / "target_portfolio.csv")
    if target is None:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "MANUAL_TARGET_COMPARISON_UNAVAILABLE",
                f"target_portfolio.csv could not be read for manual-sheet comparison: {target_error}",
            )
        )
    elif not missing and set(_MANUAL_CORE_FIELDS).issubset(target.columns):
        manual_records = frame.to_dict("records")
        target_records = target.to_dict("records")
        if len(manual_records) != len(target_records):
            mismatch = "row count differs"
        else:
            mismatch = _first_row_mismatch(
                manual_records,
                target_records,
                _MANUAL_CORE_FIELDS,
            )
        if mismatch:
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    "MANUAL_TRADE_SHEET_TARGET_MISMATCH",
                    f"manual_trade_sheet.csv core fields differ from target_portfolio.csv: {mismatch}.",
                )
            )
    return findings


def _target_plan_values(
    target_plan: dict[str, Any],
    row_count: int,
) -> tuple[dict[str, float] | None, list[ReadinessFinding]]:
    findings: list[ReadinessFinding] = []
    capital = _finite_number(target_plan.get("capital"))
    cash_buffer_pct = _finite_number(target_plan.get("cash_buffer_pct"))
    lot_size = _integer_value(target_plan.get("lot_size"))
    target_count = _integer_value(target_plan.get("target_count"))
    total_target_weight = _finite_number(target_plan.get("total_target_weight"))
    estimated_exposure = _finite_number(target_plan.get("estimated_gross_exposure"))
    estimated_cash = _finite_number(target_plan.get("estimated_cash_buffer"))
    if capital is None or capital <= 0:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "TARGET_PORTFOLIO_INVALID_CAPITAL",
                "target_portfolio.json capital must be a positive finite number.",
            )
        )
    if cash_buffer_pct is None or not 0 <= cash_buffer_pct < 1:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "TARGET_PORTFOLIO_INVALID_CASH_BUFFER",
                "target_portfolio.json cash_buffer_pct must be in [0, 1).",
            )
        )
    if lot_size is None or lot_size <= 0:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "TARGET_PORTFOLIO_INVALID_LOT_SIZE",
                "target_portfolio.json lot_size must be a positive integer.",
            )
        )
    if target_count != row_count:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "TARGET_PORTFOLIO_TARGET_COUNT_MISMATCH",
                "target_portfolio.json target_count must equal the number of JSON rows.",
            )
        )
    for key, value in (
        ("total_target_weight", total_target_weight),
        ("estimated_gross_exposure", estimated_exposure),
        ("estimated_cash_buffer", estimated_cash),
    ):
        if value is None or value < 0:
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    "TARGET_PORTFOLIO_INVALID_SUMMARY",
                    f"target_portfolio.json {key} must be a non-negative finite number.",
                )
            )
    if findings:
        return None, findings
    return (
        {
            "capital": float(capital),
            "cash_buffer_pct": float(cash_buffer_pct),
            "lot_size": float(lot_size),
        },
        findings,
    )


def _target_row_findings(
    records: list[dict[str, Any]],
    *,
    capital: float,
    cash_buffer_pct: float,
    lot_size: int,
    max_position_pct: float,
    target_plan: dict[str, Any],
) -> list[ReadinessFinding]:
    findings: list[ReadinessFinding] = []
    deployable_capital = capital * (1 - cash_buffer_pct)
    symbols: set[str] = set()
    weights: list[float] = []
    costs: list[float] = []

    for index, record in enumerate(records, start=1):
        symbol = str(record.get("symbol") or "").strip()
        if not symbol or symbol in symbols:
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    "TARGET_PORTFOLIO_INVALID_SYMBOL",
                    f"Target row {index} must have a unique non-empty symbol.",
                )
            )
        symbols.add(symbol)

        price = _finite_number(record.get("latest_price"))
        if price is None or price <= 0:
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    "TARGET_PORTFOLIO_INVALID_PRICE",
                    f"Target row {index} ({symbol or 'missing'}) latest_price must be greater than zero.",
                )
            )

        weight = _finite_number(record.get("target_weight"))
        if weight is None or not 0 <= weight <= 1:
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    "TARGET_PORTFOLIO_INVALID_WEIGHT",
                    f"Target row {index} ({symbol or 'missing'}) target_weight must be in [0, 1].",
                )
            )
        else:
            weights.append(weight)
            if weight > max_position_pct + 1e-12:
                findings.append(
                    ReadinessFinding(
                        "BLOCK",
                        "TARGET_WEIGHT_EXCEEDS_RISK_BUDGET",
                        f"Target row {index} ({symbol}) weight exceeds max_position_pct.",
                    )
                )

        quantities: dict[str, int] = {}
        for field in ("target_quantity", "current_quantity"):
            quantity = _integer_value(record.get(field))
            if quantity is None or quantity < 0:
                findings.append(
                    ReadinessFinding(
                        "BLOCK",
                        "TARGET_PORTFOLIO_INVALID_QUANTITY",
                        f"Target row {index} ({symbol or 'missing'}) {field} must be a non-negative integer.",
                    )
                )
                continue
            quantities[field] = quantity
            if quantity % lot_size:
                findings.append(
                    ReadinessFinding(
                        "BLOCK",
                        "TARGET_QUANTITY_NOT_LOT_ALIGNED",
                        f"Target row {index} ({symbol}) {field} is not divisible by lot_size {lot_size}.",
                    )
                )
        quantity_delta = _integer_value(record.get("quantity_delta"))
        if quantity_delta is None:
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    "TARGET_PORTFOLIO_INVALID_QUANTITY",
                    f"Target row {index} ({symbol or 'missing'}) quantity_delta must be an integer.",
                )
            )
        else:
            quantities["quantity_delta"] = quantity_delta
            if quantity_delta % lot_size:
                findings.append(
                    ReadinessFinding(
                        "BLOCK",
                        "TARGET_QUANTITY_NOT_LOT_ALIGNED",
                        f"Target row {index} ({symbol}) quantity_delta is not divisible by lot_size {lot_size}.",
                    )
                )
        if set(quantities) == {"target_quantity", "current_quantity", "quantity_delta"} and (
            quantities["quantity_delta"]
            != quantities["target_quantity"] - quantities["current_quantity"]
        ):
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    "TARGET_PORTFOLIO_QUANTITY_MISMATCH",
                    f"Target row {index} ({symbol}) quantity_delta does not equal target minus current quantity.",
                )
            )

        target_value = _finite_number(record.get("target_value"))
        estimated_cost = _finite_number(record.get("estimated_cost"))
        if target_value is None or target_value < 0:
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    "TARGET_PORTFOLIO_INVALID_TARGET_VALUE",
                    f"Target row {index} ({symbol or 'missing'}) target_value must be non-negative and finite.",
                )
            )
        elif (
            weight is not None
            and 0 <= weight <= 1
            and not _amount_close(
                target_value,
                deployable_capital * weight,
            )
        ):
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    "TARGET_PORTFOLIO_TARGET_VALUE_MISMATCH",
                    f"Target row {index} ({symbol}) target_value does not match deployable capital times weight.",
                )
            )
        if estimated_cost is None or estimated_cost < 0:
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    "TARGET_PORTFOLIO_INVALID_ESTIMATED_COST",
                    f"Target row {index} ({symbol or 'missing'}) estimated_cost must be non-negative and finite.",
                )
            )
        else:
            costs.append(estimated_cost)
            target_quantity = quantities.get("target_quantity")
            if (
                price is not None
                and price > 0
                and target_quantity is not None
                and not _amount_close(
                    estimated_cost,
                    price * target_quantity,
                )
            ):
                findings.append(
                    ReadinessFinding(
                        "BLOCK",
                        "TARGET_PORTFOLIO_ESTIMATED_COST_MISMATCH",
                        f"Target row {index} ({symbol}) estimated_cost does not match price times target quantity.",
                    )
                )
            if target_value is not None and estimated_cost > target_value + 0.01:
                findings.append(
                    ReadinessFinding(
                        "BLOCK",
                        "TARGET_PORTFOLIO_TARGET_VALUE_EXCEEDED",
                        f"Target row {index} ({symbol}) estimated_cost exceeds target_value.",
                    )
                )

        for field in ("score", "avg_amount_20d", "estimated_participation_rate"):
            value = _finite_number(record.get(field))
            invalid = value is None
            if field != "score" and value is not None:
                invalid = value < 0 or (field == "estimated_participation_rate" and value > 1)
            if invalid:
                findings.append(
                    ReadinessFinding(
                        "BLOCK",
                        "TARGET_PORTFOLIO_INVALID_NUMERIC_FIELD",
                        f"Target row {index} ({symbol or 'missing'}) has an invalid {field}.",
                    )
                )

    total_weight = sum(weights)
    total_cost = sum(costs)
    if total_weight > 1 + 1e-12:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "TARGET_PORTFOLIO_WEIGHT_CAP_EXCEEDED",
                "Target portfolio weights exceed 100%.",
            )
        )
    if total_cost > capital + 0.01:
        findings.append(
            ReadinessFinding(
                "BLOCK",
                "TARGET_PORTFOLIO_CAPITAL_EXCEEDED",
                "Target portfolio estimated gross exposure exceeds approved planning capital.",
            )
        )

    expected_summaries = (
        ("total_target_weight", total_weight, False),
        ("estimated_gross_exposure", total_cost, True),
        ("estimated_cash_buffer", max(capital - total_cost, 0.0), True),
    )
    for field, expected, amount in expected_summaries:
        actual = _finite_number(target_plan.get(field))
        matches = actual is not None and (
            _amount_close(actual, expected)
            if amount
            else math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12)
        )
        if not matches:
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    "TARGET_PORTFOLIO_SUMMARY_MISMATCH",
                    f"target_portfolio.json {field} does not match its rows.",
                )
            )
    return findings


def _first_row_mismatch(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    fields: tuple[str, ...],
) -> str:
    for index, (left_row, right_row) in enumerate(zip(left, right), start=1):
        for field in fields:
            left_value = left_row.get(field)
            right_value = right_row.get(field)
            if field in _TARGET_NUMERIC_FIELDS:
                left_number = _finite_number(left_value)
                right_number = _finite_number(right_value)
                if left_number is None or right_number is None:
                    matches = left_number is None and right_number is None
                elif field in _TARGET_INTEGER_FIELDS:
                    matches = _integer_value(left_value) == _integer_value(right_value)
                else:
                    matches = math.isclose(left_number, right_number, rel_tol=1e-9, abs_tol=1e-12)
            else:
                matches = str(left_value or "").strip() == str(right_value or "").strip()
            if not matches:
                return f"row {index} field {field}"
    return ""


def _read_csv(path: Path) -> tuple[pd.DataFrame | None, str | None]:
    if not path.exists() or path.stat().st_size == 0:
        return None, "file is missing or empty"
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False), None
    except (OSError, UnicodeDecodeError, ValueError, pd.errors.ParserError) as exc:
        return None, str(exc)


def _read_json_object(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists() or path.stat().st_size == 0:
        return None, "file is missing or empty"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, "top-level JSON value is not an object"
    return payload, None


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _integer_value(value: Any) -> int | None:
    number = _finite_number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _amount_close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=0.01)


def _rows_with_flags(frame: pd.DataFrame, watched: set[str]) -> list[tuple[str, set[str]]]:
    rows = []
    for record in frame.to_dict("records"):
        flags = _parse_risk_flags(record.get("risk_flags"))
        matched = flags & watched
        if matched:
            rows.append((str(record.get("symbol", "")), matched))
    return rows


def _parse_risk_flags(value: Any) -> set[str]:
    if value is None or pd.isna(value):
        return set()
    raw = str(value).replace(",", ";")
    return {
        token.strip().upper()
        for token in raw.split(";")
        if token.strip() and token.strip().lower() not in {"none", "nan"}
    }


def _format_flag_examples(rows: list[tuple[str, set[str]]]) -> str:
    examples = [f"{symbol}:{'/'.join(sorted(flags))}" for symbol, flags in rows[:5]]
    suffix = " ..." if len(rows) > 5 else ""
    return ", ".join(examples) + suffix


def _risk_budget_findings(
    root: Path,
    expected: dict[str, Any],
) -> list[ReadinessFinding]:
    actual, error = _read_json_object(root / "risk_budget.json")
    if actual is None:
        return [
            ReadinessFinding(
                "BLOCK",
                "INVALID_RISK_BUDGET",
                f"risk_budget.json is required and must contain an object: {error}",
            )
        ]
    if not _risk_budgets_equal(actual, expected):
        return [
            ReadinessFinding(
                "BLOCK",
                "RISK_BUDGET_MISMATCH",
                "risk_budget.json does not match the deterministic readiness risk budget.",
            )
        ]
    return []


def _risk_budgets_equal(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    if set(actual) != set(expected):
        return False
    for key, expected_value in expected.items():
        actual_value = actual[key]
        if isinstance(expected_value, bool):
            if type(actual_value) is not bool or actual_value is not expected_value:
                return False
        elif isinstance(expected_value, (int, float)):
            number = _finite_number(actual_value)
            if number is None or not math.isclose(
                number,
                float(expected_value),
                rel_tol=0.0,
                abs_tol=0.0,
            ):
                return False
        elif actual_value != expected_value:
            return False
    return True


def _risk_budget(assumptions: dict[str, Any]) -> dict[str, Any]:
    max_weight = _finite_number(assumptions.get("max_weight"))
    if max_weight is None or max_weight <= 0:
        max_weight = 0.05
    return {
        "manual_reference_only": True,
        "auto_order_submission": False,
        "max_position_pct": min(max_weight, 0.05),
        "max_strategy_drawdown_stop": 0.15,
        "single_day_loss_stop": 0.02,
        "max_capital_increase_without_new_review": 0.0,
    }


def _prepare_review_materials(root: Path, *, overwrite: bool) -> None:
    manual_path = root / "manual_trade_sheet.csv"
    if overwrite or not manual_path.exists():
        _manual_trade_sheet(root).to_csv(manual_path, index=False)

    risk_path = root / "risk_budget.json"
    if overwrite or not risk_path.exists():
        assumptions = _review_assumptions(_read_json(root / "llm_review.json"))
        risk_path.write_text(
            json.dumps(_risk_budget(assumptions), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _review_assumptions(llm_review: dict[str, Any]) -> dict[str, Any]:
    snapshot = llm_review.get("snapshot")
    if not isinstance(snapshot, dict):
        return {}
    summary = snapshot.get("summary")
    if not isinstance(summary, dict):
        return {}
    assumptions = summary.get("assumptions")
    return assumptions if isinstance(assumptions, dict) else {}


def _manual_trade_sheet(root: Path) -> pd.DataFrame:
    target = root / "target_portfolio.csv"
    if target.exists() and target.stat().st_size > 0:
        sheet, _ = _read_csv(target)
        if sheet is not None:
            sheet["instruction"] = _MANUAL_ONLY_INSTRUCTION
            return sheet
        return pd.DataFrame(columns=[*_MANUAL_CORE_FIELDS, "instruction"])
    path = root / "paper_positions.csv"
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(
            columns=["symbol", "quantity", "price", "market_value", "weight", "instruction"]
        )
    positions, _ = _read_csv(path)
    if positions is None:
        return pd.DataFrame(columns=[*_MANUAL_CORE_FIELDS, "instruction"])
    wanted = [
        col for col in ["symbol", "quantity", "price", "market_value", "weight"] if col in positions
    ]
    sheet = positions[wanted].copy()
    sheet["instruction"] = _MANUAL_ONLY_INSTRUCTION
    return sheet


def _combine_decision(decisions: list[ReadinessDecision]) -> ReadinessDecision:
    if any(decision == "BLOCK" for decision in decisions):
        return "BLOCK"
    if any(decision == "WATCH" for decision in decisions):
        return "WATCH"
    return "PASS"
