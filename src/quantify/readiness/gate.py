"""Micro-live readiness gate.

The gate creates manual preparation artifacts only. It never creates broker
orders and never connects to live trading infrastructure.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from quantify.data.cache_metadata import cache_metadata_blockers

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
    "paper_state.json",
    "paper_daily_review.json",
    "paper_stability.json",
    "target_portfolio.csv",
    "run_manifest.json",
}


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
    record = ApprovalRecord(
        approval_required=approval_required,
        approved_by=approved_by,
        approved_at=datetime.now(timezone.utc).isoformat(),
        approval_notes=approval_notes,
        allowed_stage=allowed_stage,
        evidence_snapshot=_approval_evidence_snapshot(root),
    )
    root.mkdir(parents=True, exist_ok=True)
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
    paper_state = _read_json(root / "paper_state.json")
    paper_daily_review = _read_json(root / "paper_daily_review.json")
    paper_stability = _read_json(root / "paper_stability.json")
    run_manifest = _read_json(root / "run_manifest.json")
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

    if not llm_review:
        findings.append(ReadinessFinding("BLOCK", "MISSING_LLM_REVIEW", "llm_review.json is required."))
    else:
        llm_decision = str(llm_review.get("decision", "")).upper()
        if llm_decision == "BLOCK":
            findings.append(ReadinessFinding("BLOCK", "LLM_REVIEW_BLOCK", "The deterministic LLM review is BLOCK."))
        elif llm_decision == "WATCH":
            findings.append(ReadinessFinding("WATCH", "LLM_REVIEW_WATCH", "The deterministic LLM review is WATCH."))
        elif llm_decision != "PASS":
            findings.append(
                ReadinessFinding(
                    "BLOCK",
                    "UNKNOWN_LLM_REVIEW",
                    "llm_review.json decision is missing or unknown.",
                )
            )

    assumptions = ((llm_review or {}).get("snapshot") or {}).get("summary", {}).get("assumptions", {})
    if assumptions.get("demo_data_used"):
        findings.append(ReadinessFinding("BLOCK", "DEMO_DATA", "Demo data cannot support micro-live readiness."))

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
    _merge_status_finding(
        findings,
        candidate_regime_validation,
        "CANDIDATE_REGIME_VALIDATION",
        missing="candidate_regime_validation_report.json is required before micro-live readiness.",
        missing_severity="BLOCK",
    )
    findings.extend(_run_manifest_findings(run_manifest))

    observed_days = int((paper_state or {}).get("observed_days", 0))
    if not paper_state:
        findings.append(ReadinessFinding("BLOCK", "MISSING_PAPER_STATE", "paper_state.json is required."))
    elif observed_days < 20:
        findings.append(
            ReadinessFinding(
                "WATCH",
                "SHORT_PAPER_RUN",
                "Paper run is shorter than 20 observed trading days.",
            )
        )
    if (paper_state or {}).get("broker_connection") not in {None, "", "none"}:
        findings.append(ReadinessFinding("BLOCK", "BROKER_CONNECTED", "Paper artifacts must not connect to a broker."))

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
    findings.extend(_target_plan_findings(root))
    findings.extend(_manual_trade_sheet_findings(root))

    if not approval:
        findings.append(ReadinessFinding("BLOCK", "MISSING_APPROVAL", "approval_record.json is required."))
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

    risk_budget = _risk_budget(assumptions)
    return ReadinessResult(
        decision=_combine_decision([finding.severity for finding in findings]),
        findings=findings,
        risk_budget=risk_budget,
    )


def write_readiness_outputs(report_dir: str | Path) -> Path:
    root = Path(report_dir)
    root.mkdir(parents=True, exist_ok=True)
    _manual_trade_sheet(root).to_csv(root / "manual_trade_sheet.csv", index=False)
    result = evaluate_micro_live_readiness(root)
    (root / "micro_live_readiness.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "micro_live_readiness.md").write_text(result.to_markdown(), encoding="utf-8")
    (root / "risk_budget.json").write_text(
        json.dumps(result.risk_budget, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return root


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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
        "paper_state.json",
        "paper_daily_review.json",
        "paper_stability.json",
        "target_portfolio.csv",
        "target_portfolio.json",
        "run_manifest.json",
    ]
    return {
        artifact: _file_sha256(root / artifact)
        for artifact in artifacts
        if (root / artifact).exists()
    }


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
    return findings


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


def _target_plan_findings(root: Path) -> list[ReadinessFinding]:
    target = root / "target_portfolio.csv"
    if not target.exists() or target.stat().st_size == 0:
        return [
            ReadinessFinding(
                "BLOCK",
                "MISSING_TARGET_PORTFOLIO",
                "target_portfolio.csv is required before micro-live readiness.",
            )
        ]
    try:
        frame = pd.read_csv(target)
    except (OSError, pd.errors.ParserError) as exc:
        return [
            ReadinessFinding(
                "BLOCK",
                "INVALID_TARGET_PORTFOLIO",
                f"target_portfolio.csv could not be read: {exc}",
            )
        ]
    if frame.empty:
        return [
            ReadinessFinding(
                "WATCH",
                "EMPTY_TARGET_PORTFOLIO",
                "target_portfolio.csv has no target rows; confirm whether the strategy intentionally holds cash.",
            )
        ]
    if "risk_flags" not in frame:
        return [
            ReadinessFinding(
                "WATCH",
                "MISSING_TARGET_RISK_FLAGS",
                "target_portfolio.csv does not include risk_flags evidence.",
            )
        ]

    blocking_rows = _rows_with_flags(frame, _BLOCKING_TARGET_FLAGS)
    watch_rows = _rows_with_flags(frame, _WATCH_TARGET_FLAGS)
    findings: list[ReadinessFinding] = []
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
    try:
        frame = pd.read_csv(path)
    except (OSError, pd.errors.ParserError) as exc:
        return [
            ReadinessFinding(
                "BLOCK",
                "INVALID_MANUAL_TRADE_SHEET",
                f"manual_trade_sheet.csv could not be read: {exc}",
            )
        ]
    if "instruction" not in frame:
        return [
            ReadinessFinding(
                "BLOCK",
                "MANUAL_TRADE_SHEET_MISSING_INSTRUCTION",
                "manual_trade_sheet.csv must include an instruction column.",
            )
        ]
    if frame.empty:
        return []

    instructions = [str(value).strip().upper() for value in frame["instruction"].fillna("").tolist()]
    if any(not instruction for instruction in instructions):
        return [
            ReadinessFinding(
                "BLOCK",
                "MANUAL_TRADE_SHEET_NOT_MANUAL_ONLY",
                "manual_trade_sheet.csv must only contain "
                f"{_MANUAL_ONLY_INSTRUCTION}; blank instructions are not allowed.",
            )
        ]
    forbidden = {
        instruction
        for instruction in instructions
        if instruction != _MANUAL_ONLY_INSTRUCTION
    }
    forbidden_with_tokens = {
        instruction
        for instruction in forbidden
        if any(token in instruction for token in _FORBIDDEN_MANUAL_SHEET_TOKENS)
    }
    if forbidden:
        examples = ", ".join(sorted(forbidden_with_tokens or forbidden)[:5])
        return [
            ReadinessFinding(
                "BLOCK",
                "MANUAL_TRADE_SHEET_NOT_MANUAL_ONLY",
                "manual_trade_sheet.csv must only contain "
                f"{_MANUAL_ONLY_INSTRUCTION}; found {examples}.",
            )
        ]
    return []


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


def _risk_budget(assumptions: dict[str, Any]) -> dict[str, Any]:
    max_weight = float(assumptions.get("max_weight", 0.05) or 0.05)
    return {
        "manual_reference_only": True,
        "auto_order_submission": False,
        "max_position_pct": min(max_weight, 0.05),
        "max_strategy_drawdown_stop": 0.15,
        "single_day_loss_stop": 0.02,
        "max_capital_increase_without_new_review": 0.0,
    }


def _manual_trade_sheet(root: Path) -> pd.DataFrame:
    target = root / "target_portfolio.csv"
    if target.exists() and target.stat().st_size > 0:
        sheet = pd.read_csv(target)
        sheet["instruction"] = _MANUAL_ONLY_INSTRUCTION
        return sheet
    path = root / "paper_positions.csv"
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(
            columns=["symbol", "quantity", "price", "market_value", "weight", "instruction"]
        )
    positions = pd.read_csv(path)
    wanted = [col for col in ["symbol", "quantity", "price", "market_value", "weight"] if col in positions]
    sheet = positions[wanted].copy()
    sheet["instruction"] = _MANUAL_ONLY_INSTRUCTION
    return sheet


def _combine_decision(decisions: list[ReadinessDecision]) -> ReadinessDecision:
    if any(decision == "BLOCK" for decision in decisions):
        return "BLOCK"
    if any(decision == "WATCH" for decision in decisions):
        return "WATCH"
    return "PASS"
