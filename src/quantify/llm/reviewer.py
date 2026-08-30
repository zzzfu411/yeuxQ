"""LLM-ready research review and release gates.

This module keeps the LLM out of the broker path. It reads research artifacts,
applies deterministic safety checks, and produces:

1. A structured review result.
2. A Markdown report for humans.
3. A prompt pack that can be sent to an external LLM for narrative critique.

The deterministic gate is always authoritative. LLM output is advisory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from quantify.research.evidence_validation import (
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

Decision = Literal["PASS", "WATCH", "BLOCK"]
Stage = Literal["research", "paper", "micro_live_ready", "micro_live", "live"]


@dataclass(frozen=True, slots=True)
class ReviewThresholds:
    """Default release thresholds for a teaching-grade quant workflow."""

    min_n_bars: int = 120
    max_drawdown_watch: float = 0.15
    max_drawdown_block: float = 0.25
    min_sharpe_watch: float = 0.5
    max_reject_rate_watch: float = 0.20
    max_reject_rate_block: float = 0.50
    max_turnover_pct_watch: float = 0.80
    min_factor_ic_obs: int = 3
    min_factor_ic_mean_watch: float = 0.0
    min_candidate_walk_forward_positive_ratio: float = 0.60
    candidate_walk_forward_tail_watch: float = -0.05
    candidate_walk_forward_tail_block: float = -0.10
    require_out_of_sample_for_paper: bool = True
    allow_live_on_demo_data: bool = False


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    severity: Decision
    code: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }


@dataclass(frozen=True, slots=True)
class ResearchSnapshot:
    """Compact summary of one research report directory."""

    report_dir: Path
    summary: dict[str, Any]
    order_count: int = 0
    rejected_order_count: int = 0
    reject_rate: float = 0.0
    avg_turnover_pct: float = 0.0
    max_turnover_pct: float = 0.0
    factor_ic_mean: float | None = None
    factor_ic_obs: int = 0
    demo_symbols: list[str] = field(default_factory=list)
    candidate_artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    robustness_report: dict[str, Any] = field(default_factory=dict)
    walk_forward_report: dict[str, Any] = field(default_factory=dict)
    selection_safety: dict[str, dict[str, Any]] = field(default_factory=dict)
    data_audit: dict[str, Any] = field(default_factory=dict)
    run_manifest: dict[str, Any] = field(default_factory=dict)
    benchmark_report: dict[str, Any] = field(default_factory=dict)
    multiple_testing_report: dict[str, Any] = field(default_factory=dict)
    trial_registry_review: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_report_dir(cls, report_dir: str | Path) -> ResearchSnapshot:
        root = Path(report_dir)
        data_audit = _read_json(root / "data_audit.json")
        run_manifest = _read_json(root / "run_manifest.json")
        benchmark_report = _read_json(root / "benchmark_report.json")
        multiple_testing_report = _read_json(root / "multiple_testing_report.json")
        trial_registry_review = _read_json(root / "trial_registry_review.json")
        robustness_report = _read_json(root / "robustness_report.json")
        walk_forward_path = root / "walk_forward_report.json"
        candidate_walk_forward_path = root / "candidate_walk_forward_report.json"
        walk_forward_report = _read_json(walk_forward_path)
        candidate_walk_forward_report = _read_json(candidate_walk_forward_path)
        selection_safety = _selection_safety_digest(
            robustness_report,
            walk_forward_report,
            candidate_walk_forward_report,
            robustness_present=(root / "robustness_report.json").exists(),
            walk_forward_present=walk_forward_path.exists(),
            candidate_walk_forward_present=candidate_walk_forward_path.exists(),
        )
        summary_path = root / "summary.json"
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            candidate_artifacts = _candidate_artifact_digests(
                root,
                include_missing=(root / "candidate_experiment_evidence.json").exists(),
            )
        else:
            candidate_artifacts = _candidate_artifact_digests(root, include_missing=True)
            summary = _candidate_experiment_summary(root, candidate_artifacts)
        orders = _read_optional_csv(root / "orders.csv")
        positions = _read_optional_csv(root / "positions.csv")
        trades = _read_optional_csv(root / "trades.csv")
        turnover = _read_optional_csv(root / "turnover.csv")
        factor_ic = _read_optional_csv(root / "factor_ic.csv")

        order_count = len(orders)
        rejected_order_count = _count_rejected_orders(orders)
        reject_rate = rejected_order_count / order_count if order_count else 0.0
        avg_turnover_pct, max_turnover_pct = _turnover_stats(turnover)
        factor_ic_mean, factor_ic_obs = _factor_ic_stats(factor_ic)
        observed_symbols = {
            str(symbol)
            for frame in (orders, positions, trades)
            if "symbol" in frame
            for symbol in frame["symbol"].dropna().tolist()
        }
        demo_symbols = sorted(symbol for symbol in observed_symbols if symbol.startswith("DEMO"))

        return cls(
            report_dir=root,
            summary=summary,
            order_count=order_count,
            rejected_order_count=rejected_order_count,
            reject_rate=reject_rate,
            avg_turnover_pct=avg_turnover_pct,
            max_turnover_pct=max_turnover_pct,
            factor_ic_mean=factor_ic_mean,
            factor_ic_obs=factor_ic_obs,
            demo_symbols=demo_symbols,
            candidate_artifacts=candidate_artifacts,
            robustness_report=robustness_report,
            walk_forward_report=walk_forward_report,
            selection_safety=selection_safety,
            data_audit=data_audit,
            run_manifest=run_manifest,
            benchmark_report=benchmark_report,
            multiple_testing_report=multiple_testing_report,
            trial_registry_review=trial_registry_review,
        )

    @property
    def assumptions(self) -> dict[str, Any]:
        assumptions = self.summary.get("assumptions", {})
        return assumptions if isinstance(assumptions, dict) else {}

    def metric(self, name: str, default: float = 0.0) -> float:
        value = self.summary.get(name, default)
        return float(value) if isinstance(value, int | float) else default

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_dir": str(self.report_dir),
            "summary": self.summary,
            "order_count": self.order_count,
            "rejected_order_count": self.rejected_order_count,
            "reject_rate": self.reject_rate,
            "avg_turnover_pct": self.avg_turnover_pct,
            "max_turnover_pct": self.max_turnover_pct,
            "factor_ic_mean": self.factor_ic_mean,
            "factor_ic_obs": self.factor_ic_obs,
            "demo_symbols": self.demo_symbols,
            "candidate_artifacts": self.candidate_artifacts,
            "robustness_report": self.robustness_report,
            "walk_forward_report": self.walk_forward_report,
            "selection_safety": self.selection_safety,
            "data_audit": self.data_audit,
            "run_manifest": self.run_manifest,
            "benchmark_report": self.benchmark_report,
            "multiple_testing_report": self.multiple_testing_report,
            "trial_registry_review": self.trial_registry_review,
        }


@dataclass(frozen=True, slots=True)
class ReviewResult:
    decision: Decision
    intended_stage: Stage
    findings: list[ReviewFinding]
    approved_actions: list[str]
    prohibited_actions: list[str]
    missing_evidence: list[str]
    next_experiments: list[str]
    snapshot: ResearchSnapshot

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "intended_stage": self.intended_stage,
            "findings": [finding.to_dict() for finding in self.findings],
            "approved_actions": self.approved_actions,
            "prohibited_actions": self.prohibited_actions,
            "missing_evidence": self.missing_evidence,
            "next_experiments": self.next_experiments,
            "snapshot": self.snapshot.to_dict(),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# LLM-ready Quant Review: {self.decision}",
            "",
            f"- Intended stage: `{self.intended_stage}`",
            f"- Report directory: `{self.snapshot.report_dir}`",
            f"- Total return: {_pct(self.snapshot.metric('total_return'))}",
            f"- Max drawdown: {_pct(self.snapshot.metric('max_drawdown'))}",
            f"- Sharpe ratio: {self.snapshot.metric('sharpe_ratio'):.2f}",
            f"- Order reject rate: {_pct(self.snapshot.reject_rate)}",
            f"- Avg turnover per rebalance: {_pct(self.snapshot.avg_turnover_pct)}",
            f"- Max turnover per rebalance: {_pct(self.snapshot.max_turnover_pct)}",
            f"- Factor RankIC mean: {_num(self.snapshot.factor_ic_mean)}",
            f"- Factor RankIC observations: {self.snapshot.factor_ic_obs}",
            "",
            "## Report Digest",
            "",
            *self._digest_lines(),
            "",
            "## Findings",
        ]
        if self.findings:
            for finding in self.findings:
                evidence = ", ".join(f"{key}={value}" for key, value in finding.evidence.items())
                lines.extend(
                    [
                        f"- `{finding.severity}` `{finding.code}`: {finding.message}",
                        f"  Evidence: {evidence or 'n/a'}",
                        f"  Recommendation: {finding.recommendation or 'n/a'}",
                    ]
                )
        else:
            lines.append("- No blocking or watch findings.")

        lines.extend(["", "## Missing Evidence"])
        lines.extend(f"- {item}" for item in self.missing_evidence)
        lines.extend(["", "## Next Experiments"])
        lines.extend(f"- {item}" for item in self.next_experiments)
        lines.extend(["", "## Approved Actions"])
        lines.extend(f"- {action}" for action in self.approved_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {action}" for action in self.prohibited_actions)
        return "\n".join(lines) + "\n"

    def _digest_lines(self) -> list[str]:
        assumptions = self.snapshot.assumptions
        keys = [
            "data_source",
            "demo_data_used",
            "universe",
            "rebalance",
            "n_holdings",
            "max_weight",
            "in_sample_end",
            "out_sample_start",
        ]
        lines = [
            f"- {key}: `{assumptions.get(key, 'missing')}`"
            for key in keys
            if key in assumptions or key in {"in_sample_end", "out_sample_start"}
        ]
        if not lines:
            lines.append("- No explicit assumptions were recorded in summary.json.")
        audit_status = str(self.snapshot.data_audit.get("status") or "missing")
        audit_finding_codes = _data_audit_finding_codes(self.snapshot.data_audit)
        manifest_demo = _manifest_demo_data_used(self.snapshot.run_manifest)
        manifest_latest = str(self.snapshot.run_manifest.get("latest_bar_date") or "missing")
        data_version = self.snapshot.run_manifest.get("data_version", {})
        data_version = data_version if isinstance(data_version, dict) else {}
        fingerprint = str(data_version.get("csv_dataset_fingerprint") or "missing")
        logical_fingerprint = str(data_version.get("cache_logical_bar_fingerprint") or "missing")
        import_batch_id = str(data_version.get("cache_latest_import_batch_id") or "missing")
        lines.extend(
            [
                f"- data_audit_status: `{audit_status}`",
                f"- data_audit_finding_codes: `{','.join(audit_finding_codes) or 'none'}`",
                f"- run_manifest_demo_data_used: `{manifest_demo}`",
                f"- run_manifest_latest_bar_date: `{manifest_latest}`",
                f"- run_manifest_logical_bar_fingerprint: `{logical_fingerprint}`",
                f"- run_manifest_import_batch_id: `{import_batch_id}`",
                f"- run_manifest_csv_fingerprint: `{fingerprint}`",
            ]
        )
        for name in (
            "robustness_report",
            "walk_forward_report",
            "candidate_walk_forward_report",
        ):
            safety = self.snapshot.selection_safety.get(name, {})
            reasons = safety.get("reasons", [])
            reason_text = "; ".join(str(reason) for reason in reasons) or "none"
            lines.extend(
                [
                    f"- {name}_selection_safety_status: `{safety.get('status', 'MISSING')}`",
                    f"- {name}_selection_safety_reasons: `{reason_text}`",
                ]
            )
        for name, evidence in _statistical_evidence_digest(self.snapshot).items():
            reasons = evidence.get("reasons", [])
            reason_text = "; ".join(str(reason) for reason in reasons) or "none"
            lines.extend(
                [
                    f"- {name}_status: `{evidence.get('status', 'MISSING')}`",
                    f"- {name}_contract_valid: `{evidence.get('contract_valid')}`",
                    f"- {name}_contract_status: `{evidence.get('contract_status', 'MISSING')}`",
                    f"- {name}_contract_reasons: `{reason_text}`",
                ]
            )
        candidate_metrics = _candidate_walk_forward_metrics(self.snapshot)
        if candidate_metrics:
            lines.extend(
                [
                    f"- candidate_walk_forward_candidate: `{candidate_metrics.get('candidate', 'missing')}`",
                    f"- candidate_walk_forward_status: `{candidate_metrics.get('status', 'missing')}`",
                    f"- candidate_walk_forward_positive_return_ratio: `{_pct(_metric_float(candidate_metrics, 'positive_return_ratio'))}`",
                    f"- candidate_walk_forward_worst_total_return: `{_pct(_metric_float(candidate_metrics, 'worst_total_return'))}`",
                    f"- candidate_walk_forward_worst_max_drawdown: `{_pct(_metric_float(candidate_metrics, 'worst_max_drawdown'))}`",
                ]
            )
        return lines


class QuantReviewPolicy:
    """Deterministic release gate before any LLM narrative is considered."""

    def __init__(self, thresholds: ReviewThresholds | None = None) -> None:
        self.thresholds = thresholds or ReviewThresholds()

    def review(self, snapshot: ResearchSnapshot, intended_stage: Stage = "paper") -> ReviewResult:
        findings: list[ReviewFinding] = []
        findings.extend(self._data_findings(snapshot, intended_stage))
        findings.extend(self._selection_safety_findings(snapshot, intended_stage))
        findings.extend(self._statistical_evidence_findings(snapshot, intended_stage))
        findings.extend(self._validation_findings(snapshot, intended_stage))
        findings.extend(self._general_artifact_findings(snapshot))
        findings.extend(self._candidate_experiment_findings(snapshot))
        findings.extend(self._candidate_walk_forward_findings(snapshot))
        findings.extend(self._performance_findings(snapshot, intended_stage))
        findings.extend(self._execution_findings(snapshot))
        findings.extend(self._factor_findings(snapshot))

        decision = _combine_decision(findings)
        return ReviewResult(
            decision=decision,
            intended_stage=intended_stage,
            findings=findings,
            approved_actions=_approved_actions(decision, intended_stage),
            prohibited_actions=_prohibited_actions(decision, intended_stage),
            missing_evidence=_missing_evidence(snapshot, findings, intended_stage),
            next_experiments=_next_experiments(snapshot, findings, intended_stage),
            snapshot=snapshot,
        )

    def _data_findings(
        self,
        snapshot: ResearchSnapshot,
        intended_stage: Stage,
    ) -> list[ReviewFinding]:
        findings = []
        audit = snapshot.data_audit
        manifest = snapshot.run_manifest
        has_audit = bool(audit)
        has_manifest = bool(manifest)
        if not has_audit:
            findings.append(
                ReviewFinding(
                    severity="BLOCK"
                    if intended_stage in {"micro_live_ready", "micro_live", "live"}
                    else "WATCH",
                    code="MISSING_DATA_AUDIT",
                    message="data_audit.json is missing from the report evidence package.",
                    evidence={"stage": intended_stage},
                    recommendation="Run data audit and include data_audit.json before promotion review.",
                )
            )
        else:
            audit_status = str(audit.get("status", "UNKNOWN")).upper()
            audit_finding_codes = _data_audit_finding_codes(audit)
            if audit_status == "BLOCK":
                findings.append(
                    ReviewFinding(
                        severity="BLOCK",
                        code="DATA_AUDIT_BLOCK",
                        message="The data audit has a BLOCK status.",
                        evidence={
                            "status": audit_status,
                            "finding_count": len(audit.get("findings", []) or []),
                            "finding_codes": audit_finding_codes,
                        },
                        recommendation="Fix data quality blockers before strategy review or paper promotion.",
                    )
                )
            elif audit_status == "WATCH":
                findings.append(
                    ReviewFinding(
                        severity="WATCH",
                        code="DATA_AUDIT_WATCH",
                        message="The data audit has WATCH findings.",
                        evidence={
                            "status": audit_status,
                            "finding_count": len(audit.get("findings", []) or []),
                            "finding_codes": audit_finding_codes,
                        },
                        recommendation="Resolve or document audit WATCH items before promotion.",
                    )
                )
            elif audit_status != "PASS":
                findings.append(
                    ReviewFinding(
                        severity="BLOCK"
                        if intended_stage in {"micro_live_ready", "micro_live", "live"}
                        else "WATCH",
                        code="UNKNOWN_DATA_AUDIT_STATUS",
                        message="The data audit status is missing or unknown.",
                        evidence={"status": audit_status},
                        recommendation="Regenerate data_audit.json with a PASS/WATCH/BLOCK status.",
                    )
                )
            if "UNIVERSE_NOT_POINT_IN_TIME" in audit_finding_codes:
                findings.append(
                    ReviewFinding(
                        severity=(
                            "BLOCK"
                            if intended_stage in {"micro_live_ready", "micro_live", "live"}
                            else "WATCH"
                        ),
                        code="UNIVERSE_NOT_POINT_IN_TIME",
                        message=(
                            "The research universe lacks point-in-time membership evidence, so "
                            "reported performance may include survivorship bias."
                        ),
                        evidence={
                            "stage": intended_stage,
                            "audit_finding": _data_audit_finding(
                                audit,
                                "UNIVERSE_NOT_POINT_IN_TIME",
                            ),
                        },
                        recommendation=(
                            "Keep the candidate research-only until it is rerun on retained "
                            "point-in-time membership history or a delisting-aware equivalent."
                        ),
                    )
                )

        if not has_manifest:
            findings.append(
                ReviewFinding(
                    severity="BLOCK"
                    if intended_stage in {"micro_live_ready", "micro_live", "live"}
                    else "WATCH",
                    code="MISSING_RUN_MANIFEST",
                    message="run_manifest.json is missing from the report evidence package.",
                    evidence={"stage": intended_stage},
                    recommendation="Write a run manifest tying config, cache, and data version to this report.",
                )
            )
        else:
            data_version = manifest.get("data_version", {})
            if not isinstance(data_version, dict) or not data_version:
                findings.append(
                    ReviewFinding(
                        severity=(
                            "BLOCK"
                            if intended_stage in {"micro_live_ready", "micro_live", "live"}
                            else "WATCH"
                        ),
                        code="MISSING_DATA_VERSION",
                        message="The run manifest has no cache import or source-provenance metadata.",
                        evidence={"stage": intended_stage, "data_version": "missing"},
                        recommendation=(
                            "Rebuild the cache through guarded intake so the manifest records "
                            "dataset fingerprints and source-QA evidence."
                        ),
                    )
                )
            else:
                provenance_gaps = _data_provenance_gaps(data_version)
                if provenance_gaps:
                    findings.append(
                        ReviewFinding(
                            severity=(
                                "BLOCK"
                                if intended_stage in {"micro_live_ready", "micro_live", "live"}
                                else "WATCH"
                            ),
                            code="INCOMPLETE_DATA_PROVENANCE",
                            message=(
                                "Cache acquisition metadata exists, but guarded source provenance "
                                "is incomplete."
                            ),
                            evidence={"stage": intended_stage, "gaps": provenance_gaps},
                            recommendation=(
                                "Complete guarded source QA and dataset fingerprint evidence before "
                                "promotion."
                            ),
                        )
                    )

        demo_data_used = bool(snapshot.assumptions.get("demo_data_used", False))
        audit_demo = bool(audit.get("demo_data_used", False)) if has_audit else False
        manifest_demo = _manifest_demo_data_used(manifest) if has_manifest else False
        artifact_demo = bool(snapshot.demo_symbols)
        demo_data_used = demo_data_used or audit_demo or manifest_demo or artifact_demo
        if artifact_demo:
            findings.append(
                ReviewFinding(
                    severity="WATCH" if intended_stage == "research" else "BLOCK",
                    code="DEMO_SYMBOLS_IN_ARTIFACTS",
                    message="Report artifacts contain deterministic DEMO symbols.",
                    evidence={
                        "demo_symbol_count": len(snapshot.demo_symbols),
                        "examples": snapshot.demo_symbols[:10],
                        "summary_demo_data_used": bool(
                            snapshot.assumptions.get("demo_data_used", False)
                        ),
                    },
                    recommendation="Quarantine this report and rerun from a cache with no demo contamination.",
                )
            )
        if demo_data_used and intended_stage in {"micro_live_ready", "micro_live", "live"}:
            severity: Decision = "WATCH" if self.thresholds.allow_live_on_demo_data else "BLOCK"
            findings.append(
                ReviewFinding(
                    severity=severity,
                    code="DEMO_DATA_FOR_LIVE",
                    message="The report was produced with demo data and cannot justify live trading.",
                    evidence={
                        "summary_demo_data_used": bool(
                            snapshot.assumptions.get("demo_data_used", False)
                        ),
                        "audit_demo_data_used": audit_demo,
                        "manifest_demo_data_used": manifest_demo,
                        "artifact_demo_data_used": artifact_demo,
                        "stage": intended_stage,
                    },
                    recommendation="Replace demo data with audited market data and rerun the review.",
                )
            )

        n_bars = int(snapshot.metric("n_bars"))
        if n_bars < self.thresholds.min_n_bars:
            findings.append(
                ReviewFinding(
                    severity="BLOCK"
                    if intended_stage in {"micro_live_ready", "micro_live", "live"}
                    else "WATCH",
                    code="SHORT_TEST_WINDOW",
                    message="The research window is too short to support release decisions.",
                    evidence={"n_bars": n_bars, "min_n_bars": self.thresholds.min_n_bars},
                    recommendation="Extend the backtest window and include out-of-sample periods.",
                )
            )
        return findings

    def _statistical_evidence_findings(
        self,
        snapshot: ResearchSnapshot,
        intended_stage: Stage,
    ) -> list[ReviewFinding]:
        findings: list[ReviewFinding] = []
        for evidence in _statistical_evidence_digest(snapshot).values():
            code_prefix = str(evidence["code_prefix"])
            filename = str(evidence["filename"])
            if not evidence["present"]:
                if intended_stage == "research":
                    continue
                findings.append(
                    ReviewFinding(
                        severity=("WATCH" if intended_stage == "paper" else "BLOCK"),
                        code=f"MISSING_{code_prefix}_EVIDENCE",
                        message=f"{filename} is missing from the statistical evidence package.",
                        evidence={"artifact": filename, "stage": intended_stage},
                        recommendation=(
                            "Generate and validate this statistical evidence before promotion."
                        ),
                    )
                )
                continue

            if evidence["contract_valid"] is not True:
                findings.append(
                    ReviewFinding(
                        severity="BLOCK",
                        code=f"INVALID_{code_prefix}_EVIDENCE_CONTRACT",
                        message=f"{filename} does not satisfy its fail-closed evidence contract.",
                        evidence={
                            "artifact": filename,
                            "reported_status": evidence["status"],
                            "validator_status": evidence["contract_status"],
                            "reasons": evidence["reasons"],
                        },
                        recommendation=(
                            "Regenerate the artifact from retained frozen inputs and repair every "
                            "validator reason before review."
                        ),
                    )
                )
                continue

            status = str(evidence["contract_status"])
            if status == "PASS":
                continue
            severity: Decision = (
                "BLOCK"
                if intended_stage in {"micro_live_ready", "micro_live", "live"} or status == "BLOCK"
                else "WATCH"
            )
            findings.append(
                ReviewFinding(
                    severity=severity,
                    code=f"{code_prefix}_EVIDENCE_{status}",
                    message=f"{filename} has validated non-PASS status {status}.",
                    evidence={
                        "artifact": filename,
                        "status": status,
                        "stage": intended_stage,
                    },
                    recommendation=(
                        "Keep the current gate decision or downgrade it; investigate the "
                        "statistical evidence before promotion."
                    ),
                )
            )
        return findings

    def _selection_safety_findings(
        self,
        snapshot: ResearchSnapshot,
        intended_stage: Stage,
    ) -> list[ReviewFinding]:
        findings: list[ReviewFinding] = []
        severity: Decision = "WATCH" if intended_stage == "research" else "BLOCK"
        for name, code in (
            ("robustness_report", "ROBUSTNESS_SELECTION_UNSAFE"),
            ("walk_forward_report", "WALK_FORWARD_SELECTION_UNSAFE"),
            (
                "candidate_walk_forward_report",
                "CANDIDATE_WALK_FORWARD_SELECTION_UNSAFE",
            ),
        ):
            safety = snapshot.selection_safety.get(name, {})
            if safety.get("status") != "UNSAFE":
                continue
            reasons = safety.get("reasons", [])
            reasons = reasons if isinstance(reasons, list) else []
            findings.append(
                ReviewFinding(
                    severity=severity,
                    code=code,
                    message=(
                        f"{safety.get('filename', name)} does not satisfy the "
                        "selection-safe v2 contract."
                    ),
                    evidence={
                        "artifact": safety.get("filename", name),
                        "artifact_type": safety.get("artifact_type", ""),
                        "selection_safety_status": "UNSAFE",
                        "reasons": reasons,
                    },
                    recommendation=(
                        "Regenerate the report with the complete v2 protocol envelope and "
                        "repair every validator reason before promotion."
                    ),
                )
            )
        return findings

    def _general_artifact_findings(
        self,
        snapshot: ResearchSnapshot,
    ) -> list[ReviewFinding]:
        findings: list[ReviewFinding] = []
        artifacts = (
            (
                "ROBUSTNESS",
                "robustness_report.json",
                snapshot.robustness_report,
                "scenarios",
                "scenario_count",
            ),
            (
                "WALK_FORWARD",
                "walk_forward_report.json",
                snapshot.walk_forward_report,
                "windows",
                "window_count",
            ),
        )
        for code_prefix, filename, payload, items_key, count_key in artifacts:
            status = _artifact_status(payload, status_key="status")
            if status not in {"WATCH", "BLOCK"}:
                continue
            severity: Decision = "BLOCK" if status == "BLOCK" else "WATCH"
            items = payload.get(items_key, [])
            item_count = len(items) if isinstance(items, list) else 0
            findings.append(
                ReviewFinding(
                    severity=severity,
                    code=f"{code_prefix}_{status}",
                    message=f"The general {code_prefix.lower()} artifact has {status} status.",
                    evidence={
                        "artifact": filename,
                        "status": status,
                        count_key: int(payload.get(count_key, item_count) or 0),
                    },
                    recommendation=(
                        "Keep promotion blocked and repair the failed evidence before review."
                        if status == "BLOCK"
                        else "Analyze the non-PASS scenarios or windows before promotion."
                    ),
                )
            )
        return findings

    def _candidate_experiment_findings(self, snapshot: ResearchSnapshot) -> list[ReviewFinding]:
        findings: list[ReviewFinding] = []
        for name, artifact in snapshot.candidate_artifacts.items():
            status = str(artifact.get("status", "UNKNOWN")).upper()
            if status in {"PASS", ""}:
                continue
            if status == "WATCH":
                severity: Decision = "WATCH"
            else:
                severity = "BLOCK"
            findings.append(
                ReviewFinding(
                    severity=severity,
                    code=f"CANDIDATE_ARTIFACT_{status}",
                    message=f"Candidate experiment artifact `{name}` is {status}.",
                    evidence={
                        "artifact": artifact.get("filename", name),
                        "path": artifact.get("path", ""),
                        "status": status,
                    },
                    recommendation=(
                        "Repair or explain this candidate experiment artifact before treating "
                        "the run as complete."
                    ),
                )
            )
        return findings

    def _candidate_walk_forward_findings(self, snapshot: ResearchSnapshot) -> list[ReviewFinding]:
        metrics = _candidate_walk_forward_metrics(snapshot)
        if not metrics:
            return []

        findings: list[ReviewFinding] = []
        selected_candidate = str(metrics.get("candidate", "") or "unknown")
        status = str(metrics.get("status", "UNKNOWN") or "UNKNOWN").upper()
        window_count = int(metrics.get("window_count", 0) or 0)
        missing_metrics = metrics.get("missing_metrics", [])
        missing_metrics = missing_metrics if isinstance(missing_metrics, list) else []
        if missing_metrics:
            findings.append(
                ReviewFinding(
                    severity="WATCH",
                    code="CANDIDATE_WALK_FORWARD_METRICS_MISSING",
                    message="Candidate walk-forward evidence is missing tail-risk stability fields.",
                    evidence={
                        "candidate": selected_candidate,
                        "missing_metrics": missing_metrics,
                    },
                    recommendation=(
                        "Regenerate candidate_walk_forward_report.json so the selected candidate "
                        "records positive_return_ratio, worst_total_return, and worst_max_drawdown."
                    ),
                )
            )
            return findings

        if status == "BLOCK":
            findings.append(
                ReviewFinding(
                    severity="BLOCK",
                    code="SELECTED_CANDIDATE_WALK_FORWARD_BLOCK",
                    message="The selected candidate has a BLOCK walk-forward stability status.",
                    evidence={
                        "candidate": selected_candidate,
                        "status": status,
                        "window_count": window_count,
                        "block_count": int(metrics.get("block_count", 0) or 0),
                    },
                    recommendation="Do not promote this candidate; inspect failed windows and redesign the rule.",
                )
            )
        elif status == "WATCH":
            findings.append(
                ReviewFinding(
                    severity="WATCH",
                    code="SELECTED_CANDIDATE_WALK_FORWARD_WATCH",
                    message="The selected candidate has only WATCH walk-forward stability evidence.",
                    evidence={
                        "candidate": selected_candidate,
                        "status": status,
                        "window_count": window_count,
                        "watch_count": int(metrics.get("watch_count", 0) or 0),
                    },
                    recommendation="Keep the candidate in research/paper until forward windows improve.",
                )
            )

        positive_ratio = float(metrics.get("positive_return_ratio", 0.0) or 0.0)
        if positive_ratio < self.thresholds.min_candidate_walk_forward_positive_ratio:
            findings.append(
                ReviewFinding(
                    severity="WATCH",
                    code="LOW_CANDIDATE_WALK_FORWARD_POSITIVE_RATIO",
                    message="Too few candidate walk-forward windows have positive returns.",
                    evidence={
                        "candidate": selected_candidate,
                        "positive_return_ratio": positive_ratio,
                        "minimum": self.thresholds.min_candidate_walk_forward_positive_ratio,
                    },
                    recommendation=(
                        "Check whether positive performance is concentrated in only one market period."
                    ),
                )
            )

        worst_return = float(metrics.get("worst_total_return", 0.0) or 0.0)
        if worst_return <= self.thresholds.candidate_walk_forward_tail_block:
            findings.append(
                ReviewFinding(
                    severity="BLOCK",
                    code="CANDIDATE_WALK_FORWARD_TAIL_LOSS",
                    message="The selected candidate has a severe losing walk-forward window.",
                    evidence={
                        "candidate": selected_candidate,
                        "worst_total_return": worst_return,
                        "limit": self.thresholds.candidate_walk_forward_tail_block,
                    },
                    recommendation="Block promotion and analyze the tail-loss window before any paper escalation.",
                )
            )
        elif worst_return <= self.thresholds.candidate_walk_forward_tail_watch:
            findings.append(
                ReviewFinding(
                    severity="WATCH",
                    code="CANDIDATE_WALK_FORWARD_TAIL_WATCH",
                    message="The selected candidate has a material losing walk-forward window.",
                    evidence={
                        "candidate": selected_candidate,
                        "worst_total_return": worst_return,
                        "watch": self.thresholds.candidate_walk_forward_tail_watch,
                    },
                    recommendation="Add cost and drawdown stress tests around the losing forward window.",
                )
            )

        worst_drawdown = float(metrics.get("worst_max_drawdown", 0.0) or 0.0)
        if worst_drawdown >= self.thresholds.max_drawdown_block:
            findings.append(
                ReviewFinding(
                    severity="BLOCK",
                    code="CANDIDATE_WALK_FORWARD_DRAWDOWN_BLOCK",
                    message="A candidate walk-forward window breached the drawdown block limit.",
                    evidence={
                        "candidate": selected_candidate,
                        "worst_max_drawdown": worst_drawdown,
                        "limit": self.thresholds.max_drawdown_block,
                    },
                    recommendation="Lower concentration or stop the candidate until tail drawdown is repaired.",
                )
            )
        elif worst_drawdown >= self.thresholds.max_drawdown_watch:
            findings.append(
                ReviewFinding(
                    severity="WATCH",
                    code="CANDIDATE_WALK_FORWARD_DRAWDOWN_WATCH",
                    message="A candidate walk-forward window has elevated drawdown.",
                    evidence={
                        "candidate": selected_candidate,
                        "worst_max_drawdown": worst_drawdown,
                        "watch": self.thresholds.max_drawdown_watch,
                    },
                    recommendation="Stress-test position sizing and recovery time on weak forward windows.",
                )
            )
        return findings

    def _validation_findings(
        self,
        snapshot: ResearchSnapshot,
        intended_stage: Stage,
    ) -> list[ReviewFinding]:
        findings = []
        if intended_stage == "research":
            return findings
        if not self.thresholds.require_out_of_sample_for_paper:
            return findings

        assumptions = snapshot.assumptions
        in_sample_end = assumptions.get("in_sample_end")
        out_sample_start = assumptions.get("out_sample_start")
        if not in_sample_end or not out_sample_start:
            findings.append(
                ReviewFinding(
                    severity="WATCH",
                    code="MISSING_OUT_OF_SAMPLE_SPLIT",
                    message="The report does not record an explicit in-sample/out-of-sample split.",
                    evidence={
                        "in_sample_end": in_sample_end or "missing",
                        "out_sample_start": out_sample_start or "missing",
                    },
                    recommendation=(
                        "Record validation windows in summary assumptions and rerun paper-stage review."
                    ),
                )
            )
            return findings

        split_values = {
            "start": assumptions.get("start"),
            "in_sample_end": in_sample_end,
            "out_sample_start": out_sample_start,
            "end": assumptions.get("end"),
        }
        parsed = {
            key: pd.to_datetime(value, errors="coerce")
            for key, value in split_values.items()
            if value
        }
        split_is_invalid = (
            pd.isna(parsed.get("in_sample_end"))
            or pd.isna(parsed.get("out_sample_start"))
            or parsed["in_sample_end"] >= parsed["out_sample_start"]
            or (
                "start" in parsed
                and not pd.isna(parsed["start"])
                and parsed["start"] > parsed["in_sample_end"]
            )
            or (
                "end" in parsed
                and not pd.isna(parsed["end"])
                and parsed["out_sample_start"] > parsed["end"]
            )
        )
        if split_is_invalid:
            findings.append(
                ReviewFinding(
                    severity=(
                        "BLOCK"
                        if intended_stage in {"micro_live_ready", "micro_live", "live"}
                        else "WATCH"
                    ),
                    code="INVALID_OUT_OF_SAMPLE_SPLIT",
                    message="The configured in-sample/out-of-sample dates are invalid or overlap.",
                    evidence={key: value or "missing" for key, value in split_values.items()},
                    recommendation="Use ordered, non-overlapping sample windows inside the research range.",
                )
            )
            return findings

        walk_forward = snapshot.walk_forward_report
        safety = snapshot.selection_safety.get("walk_forward_report", {})
        if not walk_forward:
            walk_forward = _read_json(snapshot.report_dir / "candidate_walk_forward_report.json")
            safety = snapshot.selection_safety.get("candidate_walk_forward_report", {})
        selection_safe = safety.get("status") == "PASS"
        windows = (
            walk_forward.get("windows", [])
            if isinstance(walk_forward, dict) and selection_safe
            else []
        )
        eligible_windows = [
            item
            for item in windows
            if isinstance(item, dict)
            and str(item.get("start", "")) >= str(out_sample_start)
            and str(item.get("end", "")) >= str(item.get("start", ""))
        ]
        if not walk_forward or not eligible_windows:
            findings.append(
                ReviewFinding(
                    severity=(
                        "BLOCK"
                        if intended_stage in {"micro_live_ready", "micro_live", "live"}
                        else "WATCH"
                    ),
                    code="MISSING_OUT_OF_SAMPLE_RESULTS",
                    message="Sample split dates exist, but no walk-forward results cover the out-of-sample range.",
                    evidence={
                        "out_sample_start": out_sample_start,
                        "walk_forward_present": bool(walk_forward),
                        "selection_safety_status": safety.get("status", "MISSING"),
                        "selection_safety_reasons": safety.get("reasons", []),
                        "eligible_window_count": len(eligible_windows),
                    },
                    recommendation="Generate walk-forward windows that begin on or after out_sample_start.",
                )
            )
        return findings

    def _performance_findings(
        self,
        snapshot: ResearchSnapshot,
        intended_stage: Stage,
    ) -> list[ReviewFinding]:
        findings = []
        max_drawdown = snapshot.metric("max_drawdown")
        total_return = snapshot.metric("total_return")
        sharpe = snapshot.metric("sharpe_ratio")

        if max_drawdown >= self.thresholds.max_drawdown_block:
            findings.append(
                ReviewFinding(
                    severity="BLOCK",
                    code="DRAWDOWN_BLOCK",
                    message="Max drawdown breached the hard release limit.",
                    evidence={
                        "max_drawdown": max_drawdown,
                        "limit": self.thresholds.max_drawdown_block,
                    },
                    recommendation="Reduce concentration, lower gross exposure, or stop the strategy.",
                )
            )
        elif max_drawdown >= self.thresholds.max_drawdown_watch:
            findings.append(
                ReviewFinding(
                    severity="WATCH",
                    code="DRAWDOWN_WATCH",
                    message="Max drawdown is close to the release limit.",
                    evidence={
                        "max_drawdown": max_drawdown,
                        "watch": self.thresholds.max_drawdown_watch,
                    },
                    recommendation="Run stress tests and prepare a smaller live allocation.",
                )
            )

        if total_return <= 0:
            findings.append(
                ReviewFinding(
                    severity="BLOCK"
                    if intended_stage in {"micro_live_ready", "micro_live", "live"}
                    else "WATCH",
                    code="NON_POSITIVE_RETURN",
                    message="Backtest return is not positive after costs.",
                    evidence={"total_return": total_return},
                    recommendation="Do not promote to live until the rule has positive net expectancy.",
                )
            )

        if sharpe < self.thresholds.min_sharpe_watch:
            findings.append(
                ReviewFinding(
                    severity="WATCH",
                    code="LOW_SHARPE",
                    message="Risk-adjusted return is weak.",
                    evidence={"sharpe_ratio": sharpe, "watch": self.thresholds.min_sharpe_watch},
                    recommendation="Check whether returns are concentrated in a few lucky periods.",
                )
            )
        return findings

    def _execution_findings(self, snapshot: ResearchSnapshot) -> list[ReviewFinding]:
        findings = []
        if snapshot.reject_rate >= self.thresholds.max_reject_rate_block:
            findings.append(
                ReviewFinding(
                    severity="BLOCK",
                    code="ORDER_REJECT_BLOCK",
                    message="Too many orders are rejected by the paper broker.",
                    evidence={
                        "reject_rate": snapshot.reject_rate,
                        "limit": self.thresholds.max_reject_rate_block,
                    },
                    recommendation="Fix cash, lot-size, suspension, or price-limit constraints first.",
                )
            )
        elif snapshot.reject_rate >= self.thresholds.max_reject_rate_watch:
            findings.append(
                ReviewFinding(
                    severity="WATCH",
                    code="ORDER_REJECT_WATCH",
                    message="Order rejection rate is high.",
                    evidence={
                        "reject_rate": snapshot.reject_rate,
                        "watch": self.thresholds.max_reject_rate_watch,
                    },
                    recommendation="Inspect orders.csv and reduce unfillable target weights.",
                )
            )

        if snapshot.avg_turnover_pct >= self.thresholds.max_turnover_pct_watch:
            findings.append(
                ReviewFinding(
                    severity="WATCH",
                    code="HIGH_TURNOVER",
                    message="Average turnover per rebalance is high.",
                    evidence={
                        "avg_turnover_pct": snapshot.avg_turnover_pct,
                        "watch": self.thresholds.max_turnover_pct_watch,
                    },
                    recommendation="Lower rebalance frequency or add turnover controls.",
                )
            )
        return findings

    def _factor_findings(self, snapshot: ResearchSnapshot) -> list[ReviewFinding]:
        findings = []
        if snapshot.factor_ic_obs < self.thresholds.min_factor_ic_obs:
            findings.append(
                ReviewFinding(
                    severity="WATCH",
                    code="LOW_FACTOR_IC_OBS",
                    message="Too few RankIC observations are available.",
                    evidence={
                        "factor_ic_obs": snapshot.factor_ic_obs,
                        "min_obs": self.thresholds.min_factor_ic_obs,
                    },
                    recommendation="Evaluate factors over more rebalance dates.",
                )
            )
            return findings

        if (
            snapshot.factor_ic_mean is not None
            and snapshot.factor_ic_mean <= self.thresholds.min_factor_ic_mean_watch
        ):
            findings.append(
                ReviewFinding(
                    severity="WATCH",
                    code="NON_POSITIVE_FACTOR_IC",
                    message="Average RankIC is not positive.",
                    evidence={"factor_ic_mean": snapshot.factor_ic_mean},
                    recommendation="Do not trust selection quality until factor direction is repaired.",
                )
            )
        return findings


@dataclass(frozen=True, slots=True)
class PromptPack:
    system: str
    user: str

    def to_markdown(self) -> str:
        return (
            "# LLM Review Prompt Pack\n\n"
            "## System\n\n"
            f"```text\n{self.system}\n```\n\n"
            "## User\n\n"
            f"```json\n{self.user}\n```\n"
        )


class LLMReviewPromptBuilder:
    """Builds a strict prompt for an external model or local LLM."""

    def build(self, result: ReviewResult) -> PromptPack:
        payload = {
            "task": "Audit a quantitative trading research report before release.",
            "hard_rule": (
                "The deterministic gate decision is authoritative. "
                "Validated selection-safety statuses and reasons are also authoritative. "
                "Benchmark, multiple-testing, and trial-registry artifacts cannot upgrade "
                "the deterministic gate even when their validated status is PASS. "
                "You may add critique, questions, and experiment ideas, but you may not "
                "upgrade BLOCK to WATCH/PASS, upgrade WATCH to PASS, or override any "
                "selection-safety status or validator reason."
            ),
            "required_output_schema": {
                "decision": "same as deterministic gate",
                "top_risks": ["short risk statements grounded in provided data"],
                "missing_evidence": ["tests or data needed before promotion"],
                "next_experiments": ["small, falsifiable research tasks"],
                "paper_stage_constraints": [
                    "constraints that keep the workflow in research/paper trading only"
                ],
                "live_trading_constraints": ["risk limits if micro-live is eventually allowed"],
            },
            "selection_safety": result.snapshot.selection_safety,
            "statistical_evidence": _statistical_evidence_digest(result.snapshot),
            "review_result": result.to_dict(),
        }
        system = (
            "You are a conservative quant research reviewer and risk officer. "
            "You never provide personalized investment advice. "
            "You reason from the supplied artifacts only, separate evidence from hypothesis, "
            "and prefer blocking live trading when data quality or execution reliability is weak."
        )
        return PromptPack(system=system, user=json.dumps(payload, ensure_ascii=False, indent=2))


def review_report(
    report_dir: str | Path,
    intended_stage: Stage = "paper",
    thresholds: ReviewThresholds | None = None,
) -> ReviewResult:
    snapshot = ResearchSnapshot.from_report_dir(report_dir)
    return QuantReviewPolicy(thresholds).review(snapshot, intended_stage=intended_stage)


def _statistical_evidence_digest(
    snapshot: ResearchSnapshot,
) -> dict[str, dict[str, Any]]:
    selection = _read_json(snapshot.report_dir / "candidate_selection.json")
    expected_candidate = str(
        selection.get("selected_candidate") or selection.get("best_candidate") or ""
    )
    research_parameters = snapshot.run_manifest.get("research_parameters", {})
    research_parameters = research_parameters if isinstance(research_parameters, dict) else {}
    expected_symbol = str(research_parameters.get("index_code") or "")
    specifications = (
        (
            "benchmark_report",
            "BENCHMARK",
            "benchmark_report.json",
            snapshot.benchmark_report,
        ),
        (
            "multiple_testing_report",
            "MULTIPLE_TESTING",
            "multiple_testing_report.json",
            snapshot.multiple_testing_report,
        ),
        (
            "trial_registry_review",
            "TRIAL_REGISTRY",
            "trial_registry_review.json",
            snapshot.trial_registry_review,
        ),
    )
    digest: dict[str, dict[str, Any]] = {}
    for name, code_prefix, filename, payload in specifications:
        path = snapshot.report_dir / filename
        if not path.is_file():
            digest[name] = {
                "filename": filename,
                "code_prefix": code_prefix,
                "present": False,
                "status": "MISSING",
                "contract_valid": None,
                "contract_status": "MISSING",
                "reasons": [f"{filename} is missing."],
                "can_upgrade_deterministic_gate": False,
            }
            continue
        if name == "benchmark_report":
            validation = validate_benchmark_payload(
                payload,
                expected_symbol=expected_symbol,
            )
        elif name == "multiple_testing_report":
            validation = validate_multiple_testing_payload(
                payload,
                expected_candidate=expected_candidate,
            )
        else:
            validation = validate_trial_registry_review_payload(
                payload,
                expected_candidate=expected_candidate,
                report_dir=snapshot.report_dir,
            )
        identity_reasons: list[str] = []
        if name == "benchmark_report" and not expected_symbol:
            identity_reasons.append(
                "run_manifest.research_parameters.index_code is required to validate "
                "benchmark identity."
            )
        if name in {"multiple_testing_report", "trial_registry_review"} and not (
            expected_candidate
        ):
            identity_reasons.append(
                "candidate_selection.selected_candidate or legacy best_candidate is required "
                "to validate candidate identity."
            )
        reasons = [*validation.reasons, *identity_reasons]
        contract_valid = validation.valid and not identity_reasons
        digest[name] = {
            "filename": filename,
            "code_prefix": code_prefix,
            "present": True,
            "status": _artifact_status(payload, status_key="status"),
            "contract_valid": contract_valid,
            "contract_status": validation.status if contract_valid else "BLOCK",
            "reasons": reasons,
            "expected_candidate": expected_candidate,
            "expected_benchmark_symbol": expected_symbol,
            "can_upgrade_deterministic_gate": False,
        }
    return digest


def _selection_safety_digest(
    robustness: dict[str, Any],
    walk_forward: dict[str, Any],
    candidate_walk_forward: dict[str, Any],
    *,
    robustness_present: bool,
    walk_forward_present: bool,
    candidate_walk_forward_present: bool,
) -> dict[str, dict[str, Any]]:
    digest: dict[str, dict[str, Any]] = {}
    if robustness_present:
        validation = validate_robustness_selection_safe_payload(robustness)
        digest["robustness_report"] = {
            "filename": "robustness_report.json",
            "artifact_type": "robustness_report",
            "status": "PASS" if validation.safe else "UNSAFE",
            "safe": validation.safe,
            "reasons": validation.reasons,
        }
    else:
        digest["robustness_report"] = {
            "filename": "robustness_report.json",
            "artifact_type": "robustness_report",
            "status": "MISSING",
            "safe": False,
            "reasons": ["robustness_report.json is missing."],
        }
    for name, filename, payload, present, artifact_type in (
        (
            "walk_forward_report",
            "walk_forward_report.json",
            walk_forward,
            walk_forward_present,
            WALK_FORWARD_ARTIFACT,
        ),
        (
            "candidate_walk_forward_report",
            "candidate_walk_forward_report.json",
            candidate_walk_forward,
            candidate_walk_forward_present,
            CANDIDATE_WALK_FORWARD_ARTIFACT,
        ),
    ):
        if not present:
            digest[name] = {
                "filename": filename,
                "artifact_type": artifact_type,
                "status": "MISSING",
                "safe": False,
                "reasons": [f"{filename} is missing."],
            }
            continue
        validation = validate_selection_safe_payload(
            payload,
            artifact_type=artifact_type,
        )
        digest[name] = {
            "filename": filename,
            "artifact_type": artifact_type,
            "status": "PASS" if validation.safe else "UNSAFE",
            "safe": validation.safe,
            "reasons": validation.reasons,
        }
    return digest


def _candidate_artifact_digests(
    root: Path,
    *,
    include_missing: bool,
) -> dict[str, dict[str, Any]]:
    artifacts = {
        "candidate_experiment_evidence": ("candidate_experiment_evidence.json", "status"),
        "candidate_walk_forward": ("candidate_walk_forward_report.json", "status"),
        "candidate_factor_diagnostics": ("candidate_factor_diagnostics.json", "status"),
        "candidate_regime_validation": ("candidate_regime_validation_report.json", "status"),
        "candidate_selection": ("candidate_selection.json", "status"),
    }
    out: dict[str, dict[str, Any]] = {}
    for name, (filename, status_key) in artifacts.items():
        path = root / filename
        if not path.exists():
            if include_missing:
                out[name] = {
                    "filename": filename,
                    "path": str(path),
                    "status": "MISSING",
                }
            continue
        payload = _read_json(path)
        out[name] = {
            "filename": filename,
            "path": str(path),
            "status": _artifact_status(payload, status_key=status_key),
            "best_candidate": payload.get("selected_candidate", payload.get("best_candidate", "")),
            "selected_candidate": payload.get(
                "selected_candidate", payload.get("best_candidate", "")
            ),
            "top_candidate": payload.get("top_candidate", payload.get("best_candidate", "")),
            "candidate_count": payload.get("candidate_count", ""),
            "window_count": payload.get("window_count", ""),
            "blockers": payload.get("blockers", []),
            "watch_items": payload.get("watch_items", []),
            "warnings": payload.get("warnings", []),
        }
    return out


def _candidate_experiment_summary(
    root: Path,
    candidate_artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    selection = _read_json(root / "candidate_selection.json")
    walk_forward = _read_json(root / "candidate_walk_forward_report.json")
    best_candidate = str(
        selection.get("selected_candidate")
        or selection.get("best_candidate")
        or walk_forward.get("best_candidate")
        or ""
    )
    summary = _selected_candidate_metrics(walk_forward, best_candidate)
    evidence = _read_json(root / "candidate_experiment_evidence.json")
    assumptions = _candidate_assumptions(evidence, best_candidate)
    summary["assumptions"] = assumptions
    summary["candidate_artifacts"] = candidate_artifacts
    summary["risk_notice"] = (
        "Candidate experiment evidence is research/paper only and does not guarantee profit."
    )
    return summary


def _selected_candidate_metrics(payload: dict[str, Any], best_candidate: str) -> dict[str, Any]:
    summaries = payload.get("summaries", []) if isinstance(payload, dict) else []
    selected = next(
        (
            item
            for item in summaries
            if isinstance(item, dict) and str(item.get("candidate", "")) == best_candidate
        ),
        None,
    )
    if not isinstance(selected, dict):
        selected = summaries[0] if summaries and isinstance(summaries[0], dict) else {}
    missing_metrics = [
        key
        for key in ("positive_return_ratio", "worst_total_return", "worst_max_drawdown")
        if key not in selected
    ]
    return {
        "candidate": str(selected.get("candidate") or best_candidate or ""),
        "candidate_walk_forward_status": str(
            selected.get("status") or payload.get("status") or "UNKNOWN"
        ),
        "candidate_walk_forward_window_count": int(
            selected.get("window_count", payload.get("window_count", 0)) or 0
        ),
        "candidate_walk_forward_pass_count": int(selected.get("pass_count", 0) or 0),
        "candidate_walk_forward_watch_count": int(selected.get("watch_count", 0) or 0),
        "candidate_walk_forward_block_count": int(selected.get("block_count", 0) or 0),
        "candidate_walk_forward_positive_return_ratio": float(
            selected.get("positive_return_ratio", 0.0) or 0.0
        ),
        "candidate_walk_forward_worst_total_return": float(
            selected.get("worst_total_return", 0.0) or 0.0
        ),
        "candidate_walk_forward_worst_max_drawdown": float(
            selected.get("worst_max_drawdown", 0.0) or 0.0
        ),
        "candidate_walk_forward_missing_metrics": missing_metrics,
        "total_return": float(selected.get("avg_total_return", 0.0) or 0.0),
        "max_drawdown": float(selected.get("avg_max_drawdown", 0.0) or 0.0),
        "sharpe_ratio": float(selected.get("avg_sharpe_ratio", 0.0) or 0.0),
        "n_bars": int(payload.get("window_count", 0) or 0),
    }


def _candidate_assumptions(evidence: dict[str, Any], best_candidate: str) -> dict[str, Any]:
    copied = evidence.get("copied_artifacts", []) if isinstance(evidence, dict) else []
    summary_path = _copied_destination(copied, "summary")
    summary = _read_json(Path(summary_path)) if summary_path else {}
    assumptions = summary.get("assumptions", {}) if isinstance(summary, dict) else {}
    if not isinstance(assumptions, dict):
        assumptions = {}
    return {
        **assumptions,
        "review_mode": "candidate_experiment",
        "candidate": best_candidate,
        "notice": "Candidate experiment review; LLM remains advisory and cannot upgrade deterministic gates.",
    }


def _copied_destination(copied: Any, name: str) -> str:
    if not isinstance(copied, list):
        return ""
    for item in copied:
        if isinstance(item, dict) and item.get("name") == name:
            return str(item.get("destination", ""))
    return ""


def _artifact_status(payload: dict[str, Any], *, status_key: str) -> str:
    value = payload.get(status_key, payload.get("decision", "UNKNOWN"))
    text = str(value or "UNKNOWN").upper()
    if text in {"PASS", "WATCH", "BLOCK"}:
        return text
    return "UNKNOWN"


def _data_audit_finding_codes(audit: dict[str, Any]) -> list[str]:
    codes = {
        str(item.get("code", "")).strip()
        for item in audit.get("findings", []) or []
        if isinstance(item, dict) and str(item.get("code", "")).strip()
    }
    return sorted(codes)


def _data_audit_finding(audit: dict[str, Any], code: str) -> dict[str, Any]:
    for item in audit.get("findings", []) or []:
        if isinstance(item, dict) and str(item.get("code", "")).strip() == code:
            return item
    return {}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _missing_evidence(
    snapshot: ResearchSnapshot,
    findings: list[ReviewFinding],
    intended_stage: Stage,
) -> list[str]:
    items: list[str] = []
    assumptions = snapshot.assumptions
    if intended_stage != "research" and (
        not assumptions.get("in_sample_end") or not assumptions.get("out_sample_start")
    ):
        items.append("Explicit in-sample and out-of-sample validation windows.")
    if any(finding.code == "MISSING_OUT_OF_SAMPLE_RESULTS" for finding in findings):
        items.append("Walk-forward results covering the recorded out-of-sample period.")
    if "demo_data_used" not in assumptions:
        items.append("Whether demo data or audited market data was used.")
    elif assumptions.get("demo_data_used"):
        items.append("A rerun on audited real market data.")
    if not snapshot.data_audit:
        items.append("data_audit.json proving the market data quality gate result.")
    if not snapshot.run_manifest:
        items.append("run_manifest.json tying the report to config, cache, and data version.")
    if any(
        finding.code in {"MISSING_DATA_VERSION", "INCOMPLETE_DATA_PROVENANCE"}
        for finding in findings
    ):
        items.append("Cache import metadata with dataset fingerprints and source-QA provenance.")
    if any(finding.code == "UNIVERSE_NOT_POINT_IN_TIME" for finding in findings):
        items.append(
            "Point-in-time universe membership snapshots with retained provenance; "
            "current-snapshot results remain research-only."
        )
    if any(finding.code == "CANDIDATE_WALK_FORWARD_METRICS_MISSING" for finding in findings):
        items.append("Candidate walk-forward tail-risk metrics for the selected candidate.")
    if snapshot.factor_ic_obs < 12:
        items.append("More RankIC observations across multiple rebalance periods.")
    if snapshot.order_count == 0:
        items.append("Paper-broker order logs proving the strategy can produce executable orders.")
    robustness_scenarios = snapshot.robustness_report.get("scenarios", [])
    robustness_scenario_names = {
        str(item.get("name", "")) for item in robustness_scenarios if isinstance(item, dict)
    }
    if (
        not any(finding.code == "HIGH_TURNOVER" for finding in findings)
        and "high_cost" not in robustness_scenario_names
    ):
        items.append(
            "A turnover stress test with higher transaction cost and slippage assumptions."
        )
    if not snapshot.robustness_report:
        items.append(
            "Parameter perturbation tests around holdings count, max weight, and rebalance cadence."
        )
    statistical_evidence = _statistical_evidence_digest(snapshot)
    statistical_requirements = {
        "benchmark_report": (
            "A valid PASS benchmark_report.json using the reviewed total-return benchmark "
            "identified by run_manifest.research_parameters.index_code."
        ),
        "multiple_testing_report": (
            "A valid PASS multiple_testing_report.json with DSR and CSCV/PBO diagnostics "
            "for the deterministically selected candidate."
        ),
        "trial_registry_review": (
            "A valid PASS trial_registry_review.json proving append-only preregistration and "
            "exact artifact hash bindings."
        ),
    }
    for name, requirement in statistical_requirements.items():
        evidence = statistical_evidence[name]
        if evidence["contract_valid"] is not True or evidence["contract_status"] != "PASS":
            items.append(requirement)
    return _dedupe(items)


def _next_experiments(
    snapshot: ResearchSnapshot,
    findings: list[ReviewFinding],
    intended_stage: Stage,
) -> list[str]:
    finding_codes = {finding.code for finding in findings}
    experiments: list[str] = []
    if "MISSING_OUT_OF_SAMPLE_SPLIT" in finding_codes:
        experiments.append(
            "Define explicit in-sample and out-of-sample windows before the next paper review."
        )
    elif "INVALID_OUT_OF_SAMPLE_SPLIT" in finding_codes:
        experiments.append("Correct the overlapping or invalid validation-window dates.")
    elif "MISSING_OUT_OF_SAMPLE_RESULTS" in finding_codes:
        experiments.append(
            "Generate walk-forward results that cover the recorded out-of-sample period."
        )
    elif intended_stage == "research" and not snapshot.walk_forward_report:
        experiments.append(
            "Run an out-of-sample review and record validation windows in summary assumptions."
        )

    robustness_scenarios = snapshot.robustness_report.get("scenarios", [])
    robustness_scenario_names = {
        str(item.get("name", "")) for item in robustness_scenarios if isinstance(item, dict)
    }
    if "high_cost" not in robustness_scenario_names:
        experiments.append(
            "Run a higher-cost stress test with doubled slippage and commission assumptions."
        )
    if not snapshot.robustness_report:
        experiments.append(
            "Perturb n_holdings and max_weight to check whether performance survives small rule changes."
        )
    if {"ROBUSTNESS_WATCH", "ROBUSTNESS_BLOCK"} & finding_codes:
        experiments.append(
            "Compare the non-PASS robustness scenarios and isolate the unstable assumptions."
        )
    if {"WALK_FORWARD_WATCH", "WALK_FORWARD_BLOCK"} & finding_codes:
        experiments.append(
            "Analyze the non-PASS walk-forward windows and identify the failing market regimes."
        )
    if snapshot.metric("max_drawdown") >= 0.10 or "DRAWDOWN_WATCH" in finding_codes:
        experiments.append(
            "Stress-test drawdown by reducing gross exposure and comparing recovery time."
        )
    if snapshot.reject_rate > 0 or "ORDER_REJECT_WATCH" in finding_codes:
        experiments.append(
            "Inspect rejected orders and rerun with smaller target weights or cash buffers."
        )
    if snapshot.avg_turnover_pct > 0.30 or "HIGH_TURNOVER" in finding_codes:
        experiments.append("Test lower rebalance frequency or turnover caps.")
    if snapshot.factor_ic_mean is None or snapshot.factor_ic_mean <= 0.02:
        experiments.append("Break down RankIC by factor to identify weak or inverted components.")
    if snapshot.assumptions.get("demo_data_used", False):
        experiments.append(
            "Replace demo data with real cached A-share data before any promotion review."
        )
    if {"MISSING_DATA_VERSION", "INCOMPLETE_DATA_PROVENANCE"} & finding_codes:
        experiments.append(
            "Reimport the dataset through guarded intake and verify its recorded provenance hashes."
        )
    if "UNIVERSE_NOT_POINT_IN_TIME" in finding_codes:
        experiments.append(
            "Rerun the candidate on point-in-time membership history or a delisting-aware broad "
            "panel, then compare return, drawdown, and turnover to quantify survivorship bias."
        )
    if "CANDIDATE_WALK_FORWARD_METRICS_MISSING" in finding_codes:
        experiments.append(
            "Regenerate candidate walk-forward evidence with positive-return ratio and tail-loss fields."
        )
    if "LOW_CANDIDATE_WALK_FORWARD_POSITIVE_RATIO" in finding_codes:
        experiments.append(
            "Compare the selected candidate across each forward window to find where returns vanish."
        )
    if "CANDIDATE_WALK_FORWARD_TAIL_WATCH" in finding_codes or (
        "CANDIDATE_WALK_FORWARD_TAIL_LOSS" in finding_codes
    ):
        experiments.append(
            "Run a tail-window post-mortem for the worst candidate walk-forward period."
        )
    if (
        "CANDIDATE_WALK_FORWARD_DRAWDOWN_WATCH" in finding_codes
        or "CANDIDATE_WALK_FORWARD_DRAWDOWN_BLOCK" in finding_codes
    ):
        experiments.append(
            "Replay weak candidate walk-forward windows with smaller position caps and turnover limits."
        )
    statistical_evidence = _statistical_evidence_digest(snapshot)
    if statistical_evidence["benchmark_report"]["contract_status"] != "PASS" or (
        statistical_evidence["benchmark_report"]["contract_valid"] is not True
    ):
        experiments.append(
            "Generate a reviewed total-return benchmark report for the run-manifest index and "
            "retain every hashed input."
        )
    if statistical_evidence["multiple_testing_report"]["contract_status"] != "PASS" or (
        statistical_evidence["multiple_testing_report"]["contract_valid"] is not True
    ):
        experiments.append(
            "Freeze candidate return columns, then run DSR and CSCV/PBO multiple-testing diagnostics."
        )
    if statistical_evidence["trial_registry_review"]["contract_status"] != "PASS" or (
        statistical_evidence["trial_registry_review"]["contract_valid"] is not True
    ):
        experiments.append(
            "Preregister the next prospective trial before observing results and review its "
            "append-only hash chain after completion."
        )
    return _dedupe(experiments)


def _candidate_walk_forward_metrics(snapshot: ResearchSnapshot) -> dict[str, Any]:
    summary = snapshot.summary
    keys = {
        "candidate_walk_forward_positive_return_ratio",
        "candidate_walk_forward_worst_total_return",
        "candidate_walk_forward_worst_max_drawdown",
        "candidate_walk_forward_status",
        "candidate_walk_forward_window_count",
    }
    if any(key in summary for key in keys):
        return {
            "candidate": summary.get("candidate") or snapshot.assumptions.get("candidate", ""),
            "status": summary.get("candidate_walk_forward_status", "UNKNOWN"),
            "window_count": summary.get("candidate_walk_forward_window_count", 0),
            "pass_count": summary.get("candidate_walk_forward_pass_count", 0),
            "watch_count": summary.get("candidate_walk_forward_watch_count", 0),
            "block_count": summary.get("candidate_walk_forward_block_count", 0),
            "positive_return_ratio": summary.get("candidate_walk_forward_positive_return_ratio"),
            "worst_total_return": summary.get("candidate_walk_forward_worst_total_return"),
            "worst_max_drawdown": summary.get("candidate_walk_forward_worst_max_drawdown"),
            "missing_metrics": summary.get("candidate_walk_forward_missing_metrics", []),
        }

    path = snapshot.report_dir / "candidate_walk_forward_report.json"
    payload = _read_json(path)
    if not payload:
        return {}
    selection = _read_json(snapshot.report_dir / "candidate_selection.json")
    best_candidate = str(
        selection.get("selected_candidate")
        or selection.get("best_candidate")
        or payload.get("best_candidate")
        or ""
    )
    selected = _selected_candidate_from_walk_forward(payload, best_candidate)
    if not selected:
        return {
            "candidate": best_candidate,
            "status": payload.get("status", "UNKNOWN"),
            "window_count": payload.get("window_count", 0),
            "pass_count": 0,
            "watch_count": 0,
            "block_count": 0,
            "positive_return_ratio": None,
            "worst_total_return": None,
            "worst_max_drawdown": None,
            "missing_metrics": [
                "positive_return_ratio",
                "worst_total_return",
                "worst_max_drawdown",
            ],
        }
    missing_metrics = [
        key
        for key in ("positive_return_ratio", "worst_total_return", "worst_max_drawdown")
        if key not in selected
    ]
    return {
        "candidate": selected.get("candidate") or best_candidate,
        "status": selected.get("status") or payload.get("status", "UNKNOWN"),
        "window_count": selected.get("window_count", payload.get("window_count", 0)),
        "pass_count": selected.get("pass_count", 0),
        "watch_count": selected.get("watch_count", 0),
        "block_count": selected.get("block_count", 0),
        "positive_return_ratio": selected.get("positive_return_ratio"),
        "worst_total_return": selected.get("worst_total_return"),
        "worst_max_drawdown": selected.get("worst_max_drawdown"),
        "missing_metrics": missing_metrics,
    }


def _selected_candidate_from_walk_forward(
    payload: dict[str, Any],
    best_candidate: str,
) -> dict[str, Any]:
    summaries = payload.get("summaries", []) if isinstance(payload, dict) else []
    selected = next(
        (
            item
            for item in summaries
            if isinstance(item, dict) and str(item.get("candidate", "")) == best_candidate
        ),
        None,
    )
    if isinstance(selected, dict):
        return selected
    if summaries and isinstance(summaries[0], dict):
        return summaries[0]
    return {}


def _metric_float(metrics: dict[str, Any], key: str) -> float:
    value = metrics.get(key, 0.0)
    return float(value) if isinstance(value, int | float) else 0.0


def _read_optional_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def _count_rejected_orders(orders: pd.DataFrame) -> int:
    if orders.empty or "status" not in orders:
        return 0
    status = orders["status"].astype(str).str.lower()
    return int((status == "rejected").sum())


def _turnover_stats(turnover: pd.DataFrame) -> tuple[float, float]:
    if turnover.empty or "turnover_pct" not in turnover:
        return 0.0, 0.0
    values = pd.to_numeric(turnover["turnover_pct"], errors="coerce").dropna()
    if values.empty:
        return 0.0, 0.0
    return float(values.mean()), float(values.max())


def _factor_ic_stats(factor_ic: pd.DataFrame) -> tuple[float | None, int]:
    if factor_ic.empty or "rank_ic" not in factor_ic:
        return None, 0
    values = pd.to_numeric(factor_ic["rank_ic"], errors="coerce").dropna()
    if values.empty:
        return None, 0
    return float(values.mean()), int(len(values))


def _combine_decision(findings: list[ReviewFinding]) -> Decision:
    if any(finding.severity == "BLOCK" for finding in findings):
        return "BLOCK"
    if any(finding.severity == "WATCH" for finding in findings):
        return "WATCH"
    return "PASS"


def _approved_actions(decision: Decision, intended_stage: Stage) -> list[str]:
    if decision == "BLOCK":
        return [
            "research_iteration",
            "paper_trading_dry_run_without_broker_credentials",
            "write_post_mortem_and_next_tests",
        ]
    if decision == "WATCH":
        return [
            "paper_trading_without_broker_credentials",
            "small_manual_observation",
            "additional_out_of_sample_tests",
        ]
    if intended_stage == "live":
        return [
            "paper_trading",
            "micro_live_with_hard_risk_limits",
            "manual_approval_before_each_release",
        ]
    return [
        "paper_trading_without_broker_credentials",
        "research_report_publication",
        "next_stage_review",
    ]


def _prohibited_actions(decision: Decision, intended_stage: Stage) -> list[str]:
    actions = [
        "unattended_live_order_submission",
        "increase_capital_without_new_review",
        "override_risk_limits_by_llm_output",
    ]
    if decision in {"BLOCK", "WATCH"} or intended_stage in {
        "research",
        "paper",
        "micro_live_ready",
    }:
        actions.extend(["connect_live_broker", "auto_promote_to_live"])
    return actions


def _pct(value: float) -> str:
    return f"{value:.2%}"


def _num(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _manifest_demo_data_used(payload: dict[str, Any]) -> bool:
    if not payload:
        return False
    if payload.get("demo_data_used") is True:
        return True
    version = payload.get("data_version", {})
    if isinstance(version, dict) and version.get("demo_data_used") is True:
        return True
    return False


def _data_provenance_gaps(data_version: dict[str, Any]) -> list[str]:
    gaps = []
    if not str(data_version.get("cache_logical_bar_fingerprint") or "").strip():
        gaps.append("cache_logical_bar_fingerprint")
    if (
        str(data_version.get("cache_logical_bar_fingerprint_algorithm") or "")
        != "sha256:quantify.logical-bars.v1"
    ):
        gaps.append("cache_logical_bar_fingerprint_algorithm")
    if not str(data_version.get("cache_latest_import_batch_id") or "").strip():
        gaps.append("cache_latest_import_batch_id")
    if str(data_version.get("cache_lineage_schema_version") or "") != "1":
        gaps.append("cache_lineage_schema_version")
    if str(data_version.get("data_source_qa_status") or "").upper() != "PASS":
        gaps.append("data_source_qa_status")
    if _data_version_uses_csv(data_version):
        if not str(data_version.get("csv_dataset_fingerprint") or "").strip():
            gaps.append("csv_dataset_fingerprint")
        if str(data_version.get("data_source_csv_qa_status") or "").upper() != "PASS":
            gaps.append("data_source_csv_qa_status")
    return gaps


def _data_version_uses_csv(data_version: dict[str, Any]) -> bool:
    routes = {
        str(data_version.get("data_source") or "").strip().lower(),
        str(data_version.get("last_import_source") or "").strip().lower(),
    }
    if routes & {"csv", "local_csv", "guarded_local_csv", "offline_csv", "tdx_csv"}:
        return True
    return any(
        str(data_version.get(key) or "").strip()
        for key in (
            "csv_dataset_fingerprint",
            "csv_validation_status",
            "csv_validation_report",
        )
    )
