"""Readiness review for pre-registered candidate experiments."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Literal

from quantify.data.offline_package import format_source_provenance
from quantify.market import build_market_context_readiness_from_payload
from quantify.research.candidate_experiment_queue import (
    CandidateExperimentQueue,
)

ReadinessDecision = Literal["PASS", "WATCH", "BLOCK"]
ExperimentReadinessStatus = Literal["READY", "BLOCKED"]
EvidenceScope = Literal["OHLCV_ONLY", "PIT_FUNDAMENTAL_REQUIRED", "UNSPECIFIED"]

HARD_REQUIRED_STAGE_NAMES = ["candidate_experiment_queue", "source_qa_preflight", "data_source_qa_review"]
HARD_BLOCKING_STAGE_NAMES = [
    "data_source_selection",
    "vendor_bars_normalization",
    "tdx_day_export",
    "data_gap_action_plan",
    "data_evidence_action_packet",
    "data_intake_router",
]
DATA_STAGE_NAMES = ["offline_data_package", "offline_data_intake"]
PROHIBITED_ACTIONS = [
    "Do not run candidate research experiments while readiness is BLOCK.",
    "Do not bypass source QA, CSV validation, import doctor, or offline intake.",
    "Do not treat experiment readiness as profitability evidence.",
    "Do not connect candidate experiments to real broker order submission.",
    "Do not run fundamental-dependent candidates while their PIT data path is BLOCK.",
]


@dataclass(frozen=True, slots=True)
class CandidateExperimentReadinessItem:
    priority: int
    candidate: str
    data_dependency: str
    evidence_path: str
    status: ExperimentReadinessStatus
    blocked_by: list[str]
    warnings: list[str]
    next_command: str
    required_artifacts: list[str]
    evidence_scope: EvidenceScope = "UNSPECIFIED"
    evidence_scope_note: str = "unspecified"
    evidence_path_status: str = "NOT_REVIEWED"
    source_provenance: str = "unspecified"
    market_context_source: str = "not_reviewed"
    market_context_status: str = "NOT_REVIEWED"
    market_context_label: str = "unknown"
    market_context_note: str = "not reviewed"
    intended_regimes: list[str] = field(default_factory=list)
    market_regime_fit_status: str = "NOT_REVIEWED"
    market_regime_fit: str = "not_reviewed"
    market_regime_fit_note: str = "not reviewed"
    required_evidence_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority": self.priority,
            "candidate": self.candidate,
            "data_dependency": self.data_dependency,
            "evidence_path": self.evidence_path,
            "evidence_scope": self.evidence_scope,
            "evidence_scope_note": self.evidence_scope_note,
            "evidence_path_status": self.evidence_path_status,
            "source_provenance": self.source_provenance,
            "market_context_source": self.market_context_source,
            "market_context_status": self.market_context_status,
            "market_context_label": self.market_context_label,
            "market_context_note": self.market_context_note,
            "intended_regimes": self.intended_regimes,
            "market_regime_fit_status": self.market_regime_fit_status,
            "market_regime_fit": self.market_regime_fit,
            "market_regime_fit_note": self.market_regime_fit_note,
            "required_evidence_notes": self.required_evidence_notes,
            "status": self.status,
            "blocked_by": self.blocked_by,
            "warnings": self.warnings,
            "next_command": self.next_command,
            "required_artifacts": self.required_artifacts,
        }


@dataclass(frozen=True, slots=True)
class CandidateExperimentReadiness:
    decision: ReadinessDecision
    as_of: str | None
    runnable_count: int
    blocked_count: int
    scope_summary: dict[str, dict[str, Any]]
    items: list[CandidateExperimentReadinessItem]
    blockers: list[str]
    watch_items: list[str]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "as_of": self.as_of,
            "runnable_count": self.runnable_count,
            "blocked_count": self.blocked_count,
            "scope_summary": self.scope_summary,
            "items": [item.to_dict() for item in self.items],
            "blockers": self.blockers,
            "watch_items": self.watch_items,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Candidate Experiment Readiness: {self.decision}",
            "",
            f"- As of: `{self.as_of or 'unspecified'}`",
            f"- Runnable experiments: {self.runnable_count}",
            f"- Blocked experiments: {self.blocked_count}",
            "",
            "## Scope Summary",
            "",
            "| scope | total | ready | blocked | first ready | note |",
            "| --- | ---: | ---: | ---: | --- | --- |",
        ]
        for scope, summary in self.scope_summary.items():
            lines.append(
                "| `{scope}` | {total} | {ready} | {blocked} | `{first_ready}` | {note} |".format(
                    scope=scope,
                    total=summary.get("total", 0),
                    ready=summary.get("ready", 0),
                    blocked=summary.get("blocked", 0),
                    first_ready=summary.get("first_ready_candidate", "") or "none",
                    note=_markdown_cell(summary.get("note", "")),
                )
            )
        lines.extend(
            [
                "",
                "## Candidate Queue",
                "",
                "| priority | candidate | scope | path | path status | market | status | source | next command | blocked by | warnings |",
                "| ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for item in self.items:
            blocked = "; ".join(item.blocked_by) if item.blocked_by else "none"
            warnings = "; ".join(item.warnings) if item.warnings else "none"
            command = item.next_command or "none"
            lines.append(
                f"| {item.priority} | `{item.candidate}` | `{item.evidence_scope}` | "
                f"`{item.evidence_path or 'none'}` | `{item.evidence_path_status}` | "
                f"`{item.market_context_source}:{item.market_context_label}:{item.market_context_status}/{item.market_regime_fit}` | "
                f"`{item.status}` | "
                f"{_markdown_cell(item.source_provenance)} | `{command}` | "
                f"{_markdown_cell(blocked)} | {_markdown_cell(warnings)} |"
            )
        lines.extend(["", "## Evidence Notes"])
        for item in self.items:
            lines.append("")
            lines.append(f"### `{item.candidate}`")
            lines.append(f"- Scope: {item.evidence_scope_note}")
            lines.append(f"- Source provenance: {item.source_provenance}")
            lines.append(
                f"- Market context: {item.market_context_source} "
                f"({item.market_context_label}, {item.market_context_status}) - {item.market_context_note}"
            )
            lines.append(
                f"- Market regime fit: {item.market_regime_fit_status} / "
                f"{item.market_regime_fit} - {item.market_regime_fit_note}"
            )
            lines.append(
                "- Intended regimes: "
                + ("; ".join(item.intended_regimes) if item.intended_regimes else "unknown")
            )
            lines.append("- Required evidence:")
            lines.extend(f"  - {note}" for note in item.required_evidence_notes)
        lines.extend(["", "## Blockers"])
        lines.extend(f"- {item}" for item in self.blockers) if self.blockers else lines.append("- None.")
        lines.extend(["", "## Watch Items"])
        lines.extend(f"- {item}" for item in self.watch_items) if self.watch_items else lines.append("- None.")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_candidate_experiment_readiness(
    queue: CandidateExperimentQueue,
    *,
    stage_statuses: dict[str, str],
    stage_messages: dict[str, str] | None = None,
    handoff_payload: dict[str, Any] | None = None,
    source_metadata_summary: dict[str, Any] | None = None,
    market_context: dict[str, Any] | None = None,
    ohlcv_package_payload: dict[str, Any] | None = None,
    as_of: str | None = None,
) -> CandidateExperimentReadiness:
    stage_blockers, stage_warnings = _stage_reviews(stage_statuses, stage_messages or {})
    path_reviews = _handoff_path_reviews(handoff_payload or {})
    source_provenance = _source_provenance(source_metadata_summary or {})
    market_review = _market_context_review(market_context, as_of=as_of)
    items = [
        _readiness_item(
            experiment,
            stage_blockers=stage_blockers,
            stage_warnings=stage_warnings,
            path_reviews=path_reviews,
            source_provenance=source_provenance,
            market_review=market_review,
            ohlcv_package_review=_ohlcv_package_review(ohlcv_package_payload or {}),
        )
        for experiment in queue.experiments
    ]
    runnable = sum(1 for item in items if item.status == "READY")
    blocked = sum(1 for item in items if item.status == "BLOCKED")
    watch_items = _watch_items(items)
    blockers = _decision_blockers(stage_blockers, items, runnable)
    decision: ReadinessDecision
    if not queue.experiments:
        decision = "WATCH"
        blockers = ["Candidate experiment queue has no experiments."]
    elif stage_blockers or runnable == 0:
        decision = "BLOCK"
    elif blocked or watch_items:
        decision = "WATCH"
    else:
        decision = "PASS"
    return CandidateExperimentReadiness(
        decision=decision,
        as_of=as_of,
        runnable_count=runnable,
        blocked_count=blocked,
        scope_summary=_scope_summary(items),
        items=items,
        blockers=blockers,
        watch_items=watch_items,
        next_actions=_next_actions(blockers, watch_items, items),
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def build_candidate_experiment_readiness_from_report(
    report_dir: str | Path,
    *,
    as_of: str | None = None,
) -> CandidateExperimentReadiness:
    root = Path(report_dir)
    queue_payload = _read_json(root / "candidate_experiment_queue.json")
    queue = _queue_from_payload(queue_payload)
    pipeline = _read_json(root / "first_million_pipeline.json")
    stages = pipeline.get("stages", []) or []
    return build_candidate_experiment_readiness(
        queue,
        stage_statuses={str(item.get("name")): str(item.get("status")) for item in stages if isinstance(item, dict)},
        stage_messages={str(item.get("name")): str(item.get("message")) for item in stages if isinstance(item, dict)},
        handoff_payload=_read_json(root / "real_data_handoff_checklist.json"),
        source_metadata_summary=_dict_payload(
            _read_json(root / "offline_data_package.json").get("source_metadata_summary")
        ),
        market_context=_market_context_from_report(root),
        ohlcv_package_payload=_read_json(root / "ohlcv_experiment_package.json"),
        as_of=as_of or str(queue_payload.get("as_of") or ""),
    )


def write_candidate_experiment_readiness(
    readiness: CandidateExperimentReadiness,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "candidate_experiment_readiness.json").write_text(
        json.dumps(readiness.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "candidate_experiment_readiness.md").write_text(
        readiness.to_markdown(),
        encoding="utf-8",
    )
    _write_candidate_experiment_readiness_matrix(readiness, root / "candidate_experiment_readiness_matrix.csv")
    return root


def _write_candidate_experiment_readiness_matrix(
    readiness: CandidateExperimentReadiness,
    path: Path,
) -> None:
    fieldnames = [
        "priority",
        "candidate",
        "data_dependency",
        "evidence_scope",
        "evidence_path",
        "evidence_path_status",
        "status",
        "first_blocker",
        "blocker_count",
        "warning_count",
        "next_command",
        "source_provenance",
        "market_context_source",
        "market_context_status",
        "market_context_label",
        "intended_regimes",
        "market_regime_fit_status",
        "market_regime_fit",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in readiness.items:
            writer.writerow(
                {
                    "priority": item.priority,
                    "candidate": item.candidate,
                    "data_dependency": item.data_dependency,
                    "evidence_scope": item.evidence_scope,
                    "evidence_path": item.evidence_path,
                    "evidence_path_status": item.evidence_path_status,
                    "status": item.status,
                    "first_blocker": item.blocked_by[0] if item.blocked_by else "",
                    "blocker_count": len(item.blocked_by),
                    "warning_count": len(item.warnings),
                    "next_command": item.next_command,
                    "source_provenance": item.source_provenance,
                    "market_context_source": item.market_context_source,
                    "market_context_status": item.market_context_status,
                    "market_context_label": item.market_context_label,
                    "intended_regimes": "; ".join(item.intended_regimes),
                    "market_regime_fit_status": item.market_regime_fit_status,
                    "market_regime_fit": item.market_regime_fit,
                }
            )


def _stage_reviews(
    stage_statuses: dict[str, str],
    stage_messages: dict[str, str],
) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    for name in HARD_REQUIRED_STAGE_NAMES:
        status = stage_statuses.get(name, "MISSING").upper()
        if status != "PASS":
            message = stage_messages.get(name, "Required stage is not PASS.")
            blockers.append(f"{name}={status}: {message}")
    for name in HARD_BLOCKING_STAGE_NAMES:
        if name not in stage_statuses:
            continue
        status = stage_statuses.get(name, "UNKNOWN").upper()
        if status == "BLOCK":
            message = stage_messages.get(name, "Upstream hard-blocking stage is BLOCK.")
            blockers.append(f"{name}=BLOCK: {message}")
    for name in DATA_STAGE_NAMES:
        status = stage_statuses.get(name, "MISSING").upper()
        message = stage_messages.get(name, "Required data stage is not PASS.")
        if status in {"BLOCK", "MISSING", "UNKNOWN"}:
            blockers.append(f"{name}={status}: {message}")
        elif status == "WATCH":
            warnings.append(f"{name}=WATCH: {message}")
    return blockers, warnings


def _readiness_item(
    experiment,
    *,
    stage_blockers: list[str],
    stage_warnings: list[str],
    path_reviews: dict[str, dict[str, Any]],
    source_provenance: str,
    market_review: dict[str, Any],
    ohlcv_package_review: dict[str, Any],
) -> CandidateExperimentReadinessItem:
    evidence_path = _evidence_path_for_dependency(experiment.data_dependency)
    blocked_by = list(stage_blockers)
    warnings = list(stage_warnings)
    market_status = str(market_review.get("status", "NOT_REVIEWED")).upper()
    market_source = str(market_review.get("source", "not_reviewed"))
    market_label = str(market_review.get("label", "unknown"))
    regime_fit = _market_regime_fit(
        source=market_source,
        label=market_label,
        market_status=market_status,
        intended_regimes=experiment.intended_regimes,
    )
    if market_status == "BLOCK":
        blocked_by.append(str(market_review.get("message", "Market context is BLOCK.")))
    elif market_status == "WATCH":
        warnings.append(str(market_review.get("message", "Market context requires review.")))
    fit_status = str(regime_fit.get("status", "NOT_REVIEWED")).upper()
    if fit_status == "BLOCK":
        blocked_by.append(str(regime_fit.get("note", "Candidate market-regime fit is BLOCK.")))
    elif fit_status == "WATCH" and market_status != "NOT_REVIEWED":
        warnings.append(str(regime_fit.get("note", "Candidate market-regime fit requires review.")))
    if experiment.data_dependency == "ohlcv_only":
        package_status = str(ohlcv_package_review.get("status", "NOT_REVIEWED")).upper()
        if package_status == "BLOCK":
            blocked_by.append(str(ohlcv_package_review.get("message", "OHLCV experiment package is BLOCK.")))
        elif package_status == "WATCH":
            warnings.append(str(ohlcv_package_review.get("message", "OHLCV experiment package requires review.")))
    path_review = path_reviews.get(evidence_path)
    if path_reviews and not path_review:
        blocked_by.append(f"{evidence_path}: evidence path is missing from real_data_handoff_checklist.json.")
    elif path_review:
        status = str(path_review.get("status", "UNKNOWN")).upper()
        if status == "BLOCK":
            blocked_by.extend(
                f"{evidence_path}: {item}"
                for item in [str(value) for value in path_review.get("blocked_by", []) or []]
            )
        elif status == "WATCH":
            warnings.append(f"{evidence_path}=WATCH: {path_review.get('next_action', 'review required')}")
        elif status != "PASS":
            blocked_by.append(f"{evidence_path}: status={status} requires review.")
    is_ready = not blocked_by
    return CandidateExperimentReadinessItem(
        priority=experiment.priority,
        candidate=experiment.candidate,
        data_dependency=experiment.data_dependency,
        evidence_path=evidence_path,
        evidence_scope=_evidence_scope_for_dependency(experiment.data_dependency),
        evidence_scope_note=_evidence_scope_note(experiment.data_dependency),
        evidence_path_status=_evidence_path_status(path_reviews, path_review),
        source_provenance=source_provenance,
        market_context_source=market_source,
        market_context_status=market_status,
        market_context_label=market_label,
        market_context_note=str(market_review.get("note", "")),
        intended_regimes=list(experiment.intended_regimes),
        market_regime_fit_status=fit_status,
        market_regime_fit=str(regime_fit.get("fit", "not_reviewed")),
        market_regime_fit_note=str(regime_fit.get("note", "")),
        required_evidence_notes=_required_evidence_notes(experiment.data_dependency, path_review),
        status="READY" if is_ready else "BLOCKED",
        blocked_by=_dedupe(blocked_by),
        warnings=_dedupe(warnings),
        next_command=experiment.command_sequence[0] if experiment.command_sequence and is_ready else "",
        required_artifacts=experiment.artifacts,
    )


def _handoff_path_reviews(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    paths = payload.get("evidence_paths", []) if isinstance(payload, dict) else []
    return {
        str(item.get("name")): item
        for item in paths
        if isinstance(item, dict) and item.get("name")
    }


def _evidence_path_for_dependency(data_dependency: str) -> str:
    return "ohlcv_minimum_path" if data_dependency == "ohlcv_only" else "pit_fundamental_candidate_path"


def _evidence_scope_for_dependency(data_dependency: str) -> EvidenceScope:
    return "OHLCV_ONLY" if data_dependency == "ohlcv_only" else "PIT_FUNDAMENTAL_REQUIRED"


def _evidence_scope_note(data_dependency: str) -> str:
    if data_dependency == "ohlcv_only":
        return (
            "OHLCV-only research scope: audited bars can launch this candidate, "
            "but they cannot support valuation or accounting-quality claims."
        )
    return (
        "PIT-fundamental research scope: audited bars plus point-in-time fundamentals "
        "must pass before this candidate can run."
    )


def _evidence_path_status(
    path_reviews: dict[str, dict[str, Any]],
    path_review: dict[str, Any] | None,
) -> str:
    if not path_reviews:
        return "NOT_REVIEWED"
    if not path_review:
        return "MISSING"
    status = str(path_review.get("status", "UNKNOWN")).upper()
    return status or "UNKNOWN"


def _required_evidence_notes(
    data_dependency: str,
    path_review: dict[str, Any] | None,
) -> list[str]:
    if path_review:
        notes = _clean_strings(path_review.get("required_evidence", []) or [])
        if notes:
            return notes
    if data_dependency == "ohlcv_only":
        return [
            "Audited OHLCV bars with source QA, non-template rows, and import doctor evidence.",
            "Explicit note that this candidate remains OHLCV-only and cannot validate fundamentals.",
        ]
    return [
        "Audited OHLCV bars plus fundamentals.csv with point-in-time provenance.",
        "Lookahead risk for value and quality fields must be resolved before candidate comparison.",
    ]


def _source_provenance(summary: dict[str, Any]) -> str:
    return format_source_provenance(summary) or "unspecified"


def _market_context_from_report(root: Path) -> dict[str, Any]:
    market_regime = _read_first_available_json(
        root / "market_regime.json",
        root / "weekly" / "market_regime.json",
    )
    if market_regime:
        artifact = _market_regime_artifact(root)
        return {"source": "market_regime", "payload": market_regime, "artifact": str(artifact)}
    snapshot = _read_json(root / "market_context_snapshot.json")
    if snapshot:
        return {
            "source": "market_context_snapshot",
            "payload": snapshot,
            "artifact": str(root / "market_context_snapshot.json"),
        }
    return {"source": "missing", "payload": {}, "artifact": str(root / "market_regime.json")}


def _market_context_review(market_context: dict[str, Any] | None, *, as_of: str | None) -> dict[str, str]:
    return build_market_context_readiness_from_payload(market_context, as_of=as_of).to_candidate_review()


def _market_regime_fit(
    *,
    source: str,
    label: str,
    market_status: str,
    intended_regimes: list[str],
) -> dict[str, str]:
    normalized_label = _normalize_regime(label)
    normalized_intended = [_normalize_regime(value) for value in intended_regimes]
    if source == "not_reviewed":
        return {
            "status": "NOT_REVIEWED",
            "fit": "not_reviewed",
            "note": "Market regime fit was not requested for this direct readiness call.",
        }
    if market_status in {"BLOCK", "MISSING"} or normalized_label == "unknown":
        return {
            "status": "WATCH",
            "fit": "insufficient_context",
            "note": "Market regime fit is not reviewable until market context is available.",
        }
    if normalized_label == "risk_off":
        return {
            "status": "BLOCK",
            "fit": "risk_off_pause",
            "note": "Current market context is risk_off; candidate experiments must pause until adverse-window evidence is reviewed.",
        }
    if normalized_label == "neutral":
        return {
            "status": "PASS" if market_status == "PASS" else "WATCH",
            "fit": "neutral_research_baseline",
            "note": "Current market context is neutral; candidate experiments may run if all separate data and evidence gates allow.",
        }
    if normalized_label in normalized_intended:
        return {
            "status": "PASS" if market_status == "PASS" else "WATCH",
            "fit": "intended_regime",
            "note": "Current market context matches the candidate's pre-registered intended regimes.",
        }
    if normalized_label == "risk_on":
        return {
            "status": "WATCH",
            "fit": "opportunistic_only",
            "note": "Current market context is risk_on but this candidate was not registered as risk-on aligned; keep as research-only.",
        }
    if normalized_label == "defensive":
        return {
            "status": "WATCH",
            "fit": "defensive_mismatch",
            "note": "Current market context is defensive; require extra drawdown and liquidity stress before launch.",
        }
    return {
        "status": "WATCH",
        "fit": "out_of_intended_regime",
        "note": "Current market context is outside the candidate's pre-registered intended regimes.",
    }


def _normalize_regime(value: object) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    if not text:
        return "unknown"
    if "risk-off" in text or "risk off" in text:
        return "risk_off"
    if "risk-on" in text or "risk on" in text:
        return "risk_on"
    if "defensive" in text or "adverse" in text:
        return "defensive"
    if "neutral" in text or "sideways" in text or "choppy" in text:
        return "neutral"
    if "recovery" in text and "risk" in text:
        return "defensive"
    if "recovery" in text:
        return "neutral"
    return text.replace("-", "_").replace(" ", "_")


def _ohlcv_package_review(payload: dict[str, Any]) -> dict[str, str]:
    if not payload:
        return {
            "status": "NOT_REVIEWED",
            "message": "",
            "note": "OHLCV experiment package preflight was not supplied.",
        }
    decision = str(payload.get("decision") or "BLOCK").upper()
    candidate = str(payload.get("candidate") or "price_volume_defensive")
    blockers = _clean_strings(payload.get("blockers", []) or [])
    watches = _clean_strings(payload.get("watch_items", []) or [])
    if decision == "PASS":
        return {
            "status": "PASS",
            "message": "",
            "note": f"OHLCV experiment package passes for {candidate}.",
        }
    if decision == "WATCH":
        return {
            "status": "WATCH",
            "message": (
                f"ohlcv_experiment_package=WATCH: {watches[0]}"
                if watches
                else "ohlcv_experiment_package=WATCH: review retained warnings before research launch."
            ),
            "note": "OHLCV package can only support guarded research, not paper/live.",
        }
    return {
        "status": "BLOCK",
        "message": (
            f"ohlcv_experiment_package=BLOCK: {blockers[0]}"
            if blockers
            else "ohlcv_experiment_package=BLOCK: OHLCV-only package preflight blocks research launch."
        ),
        "note": "OHLCV-only candidate research remains blocked until package preflight passes or watches.",
    }


def _market_regime_artifact(root: Path) -> Path:
    local = root / "market_regime.json"
    return local if local.exists() else root / "weekly" / "market_regime.json"


def _watch_items(items: list[CandidateExperimentReadinessItem]) -> list[str]:
    values: list[str] = []
    for item in items:
        values.extend(f"{item.candidate}: {warning}" for warning in item.warnings)
    return _dedupe(values)


def _decision_blockers(
    stage_blockers: list[str],
    items: list[CandidateExperimentReadinessItem],
    runnable: int,
) -> list[str]:
    if stage_blockers:
        return _dedupe(stage_blockers)
    if runnable:
        return []
    blockers: list[str] = []
    for item in items:
        blockers.extend(f"{item.candidate}: {blocker}" for blocker in item.blocked_by)
    return _dedupe(blockers)


def _scope_summary(items: list[CandidateExperimentReadinessItem]) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for scope in ["OHLCV_ONLY", "PIT_FUNDAMENTAL_REQUIRED", "UNSPECIFIED"]:
        scoped = [item for item in items if item.evidence_scope == scope]
        if not scoped and scope == "UNSPECIFIED":
            continue
        ready = [item for item in scoped if item.status == "READY"]
        blocked = [item for item in scoped if item.status == "BLOCKED"]
        summaries[scope] = {
            "total": len(scoped),
            "ready": len(ready),
            "blocked": len(blocked),
            "first_ready_candidate": ready[0].candidate if ready else "",
            "blocked_candidates": [item.candidate for item in blocked],
            "note": _scope_summary_note(scope, ready_count=len(ready), blocked_count=len(blocked)),
        }
    return summaries


def _scope_summary_note(scope: str, *, ready_count: int, blocked_count: int) -> str:
    if scope == "OHLCV_ONLY":
        if ready_count:
            return "OHLCV-only experiments may run; PIT claims remain prohibited."
        return "OHLCV-only path is not ready; fix bars/source QA/offline intake first."
    if scope == "PIT_FUNDAMENTAL_REQUIRED":
        if ready_count:
            return "PIT-dependent experiments may run only with point-in-time provenance."
        if blocked_count:
            return "PIT-dependent candidates stay parked until fundamentals provenance passes."
    return "No scope-specific routing note."


def _next_actions(
    blockers: list[str],
    watch_items: list[str],
    items: list[CandidateExperimentReadinessItem],
) -> list[str]:
    if not blockers:
        first_ready = next((item for item in sorted(items, key=lambda value: value.priority) if item.status == "READY"), None)
        actions = [
            (
                f"Run the first READY candidate experiment: {first_ready.candidate}."
                if first_ready
                else "No READY candidate experiment is available."
            )
        ]
        if any(item.status == "BLOCKED" for item in items):
            actions.append("Keep blocked candidates parked until their data-dependency path passes.")
        if watch_items:
            actions.append("Keep WATCH evidence with the experiment report and review it before paper planning.")
        return actions
    actions: list[str] = []
    if any("data_source_qa_review" in blocker for blocker in blockers):
        actions.append("Fill data_source_qa_answers.json with real vendor/export evidence.")
    if any("source_qa_preflight" in blocker for blocker in blockers):
        actions.append("Resolve source QA preflight gaps before launching candidate experiments.")
    if any("offline_data_package" in blocker for blocker in blockers):
        actions.append("Build a PASS offline data package before candidate experiments.")
    if any("offline_data_intake" in blocker for blocker in blockers):
        actions.append("Replace template CSV rows with recent real A-share daily exports and rerun offline intake.")
    if any("candidate_experiment_queue" in blocker for blocker in blockers):
        actions.append("Generate candidate_experiment_queue.json before checking experiment readiness.")
    if any("market_context=MISSING" in blocker for blocker in blockers):
        actions.append(
            "Generate cache-derived market_regime.json from audited A-share daily data, or attach a reviewed "
            "market_context_snapshot.json as temporary advisory context."
        )
    if any("ohlcv_minimum_path" in blocker for blocker in blockers):
        actions.append("Supply real non-template bars.csv and source QA evidence for the OHLCV-only path.")
    if any("ohlcv_experiment_package" in blocker for blocker in blockers):
        actions.append(
            "Make ohlcv_experiment_package.json PASS/WATCH before launching the OHLCV-only price_volume_defensive research experiment."
        )
    if any(
        item.candidate == "regime_pause_price_volume" and item.status == "READY"
        for item in items
    ):
        actions.append(
            "Keep explicit pause/resume notes with regime_pause_price_volume so the experiment stays distinct from a generic broad-trend tweak."
        )
    if any("pit_fundamental_candidate_path" in blocker for blocker in blockers):
        actions.append("Supply PIT fundamentals before running value or quality dependent candidates.")
    actions.append("Rerun first-million pipeline after hard data gates pass.")
    return _dedupe(actions)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _clean_strings(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if str(value or "").strip()]


def _dict_payload(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _read_first_available_json(*paths: Path) -> dict[str, Any]:
    for path in paths:
        payload = _read_json(path)
        if payload:
            return payload
    return {}


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _queue_from_payload(payload: dict[str, Any]) -> CandidateExperimentQueue:
    from quantify.research.candidate_experiment_queue import CandidateExperiment

    experiments = [
        CandidateExperiment(
            priority=int(item.get("priority", 99)),
            candidate=str(item.get("candidate", "")),
            data_dependency=str(item.get("data_dependency", "unknown")),
            intended_regimes=[str(value) for value in item.get("intended_regimes", []) or []],
            objective=str(item.get("objective", "")),
            rationale=str(item.get("rationale", "")),
            required_inputs=[str(value) for value in item.get("required_inputs", []) or []],
            command_sequence=[str(value) for value in item.get("command_sequence", []) or []],
            success_criteria=[str(value) for value in item.get("success_criteria", []) or []],
            falsification_tests=[str(value) for value in item.get("falsification_tests", []) or []],
            stop_conditions=[str(value) for value in item.get("stop_conditions", []) or []],
            artifacts=[str(value) for value in item.get("artifacts", []) or []],
            prohibited_actions=[str(value) for value in item.get("prohibited_actions", []) or []],
            capital_goal_fit_tests=[
                str(value) for value in item.get("capital_goal_fit_tests", []) or []
            ],
            minimum_evidence_window=_dict_payload(item.get("minimum_evidence_window")),
            risk_budget_checks=[str(value) for value in item.get("risk_budget_checks", []) or []],
            paper_entry_requirements=[
                str(value) for value in item.get("paper_entry_requirements", []) or []
            ],
            anti_overfit_controls=[str(value) for value in item.get("anti_overfit_controls", []) or []],
        )
        for item in payload.get("experiments", []) or []
        if isinstance(item, dict)
    ]
    return CandidateExperimentQueue(
        status=str(payload.get("status", "UNKNOWN")),
        as_of=str(payload.get("as_of") or "") or None,
        experiment_count=len(experiments),
        experiments=experiments,
        required_evidence_before_running=[
            str(value) for value in payload.get("required_evidence_before_running", []) or []
        ],
        prohibited_actions=[str(value) for value in payload.get("prohibited_actions", []) or []],
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
