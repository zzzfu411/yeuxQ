"""LLM-ready research review and release gates.

This module keeps the LLM out of the broker path. It reads research artifacts,
applies deterministic safety checks, and produces:

1. A structured review result.
2. A Markdown report for humans.
3. A prompt pack that can be sent to an external LLM for narrative critique.

The deterministic gate is always authoritative. LLM output is advisory.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Literal

import pandas as pd

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
    candidate_artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    data_audit: dict[str, Any] = field(default_factory=dict)
    run_manifest: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_report_dir(cls, report_dir: str | Path) -> "ResearchSnapshot":
        root = Path(report_dir)
        data_audit = _read_json(root / "data_audit.json")
        run_manifest = _read_json(root / "run_manifest.json")
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
        turnover = _read_optional_csv(root / "turnover.csv")
        factor_ic = _read_optional_csv(root / "factor_ic.csv")

        order_count = len(orders)
        rejected_order_count = _count_rejected_orders(orders)
        reject_rate = rejected_order_count / order_count if order_count else 0.0
        avg_turnover_pct, max_turnover_pct = _turnover_stats(turnover)
        factor_ic_mean, factor_ic_obs = _factor_ic_stats(factor_ic)

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
            candidate_artifacts=candidate_artifacts,
            data_audit=data_audit,
            run_manifest=run_manifest,
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
            "candidate_artifacts": self.candidate_artifacts,
            "data_audit": self.data_audit,
            "run_manifest": self.run_manifest,
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
        manifest_demo = _manifest_demo_data_used(self.snapshot.run_manifest)
        manifest_latest = str(self.snapshot.run_manifest.get("latest_bar_date") or "missing")
        data_version = self.snapshot.run_manifest.get("data_version", {})
        data_version = data_version if isinstance(data_version, dict) else {}
        fingerprint = str(data_version.get("csv_dataset_fingerprint") or "missing")
        lines.extend(
            [
                f"- data_audit_status: `{audit_status}`",
                f"- run_manifest_demo_data_used: `{manifest_demo}`",
                f"- run_manifest_latest_bar_date: `{manifest_latest}`",
                f"- run_manifest_csv_fingerprint: `{fingerprint}`",
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
        findings.extend(self._validation_findings(snapshot, intended_stage))
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
                    severity="BLOCK" if intended_stage in {"micro_live_ready", "micro_live", "live"} else "WATCH",
                    code="MISSING_DATA_AUDIT",
                    message="data_audit.json is missing from the report evidence package.",
                    evidence={"stage": intended_stage},
                    recommendation="Run data audit and include data_audit.json before promotion review.",
                )
            )
        else:
            audit_status = str(audit.get("status", "UNKNOWN")).upper()
            if audit_status == "BLOCK":
                findings.append(
                    ReviewFinding(
                        severity="BLOCK",
                        code="DATA_AUDIT_BLOCK",
                        message="The data audit has a BLOCK status.",
                        evidence={"status": audit_status, "finding_count": len(audit.get("findings", []) or [])},
                        recommendation="Fix data quality blockers before strategy review or paper promotion.",
                    )
                )
            elif audit_status == "WATCH":
                findings.append(
                    ReviewFinding(
                        severity="WATCH",
                        code="DATA_AUDIT_WATCH",
                        message="The data audit has WATCH findings.",
                        evidence={"status": audit_status, "finding_count": len(audit.get("findings", []) or [])},
                        recommendation="Resolve or document audit WATCH items before promotion.",
                    )
                )
            elif audit_status != "PASS":
                findings.append(
                    ReviewFinding(
                        severity="BLOCK" if intended_stage in {"micro_live_ready", "micro_live", "live"} else "WATCH",
                        code="UNKNOWN_DATA_AUDIT_STATUS",
                        message="The data audit status is missing or unknown.",
                        evidence={"status": audit_status},
                        recommendation="Regenerate data_audit.json with a PASS/WATCH/BLOCK status.",
                    )
                )

        if not has_manifest:
            findings.append(
                ReviewFinding(
                    severity="BLOCK" if intended_stage in {"micro_live_ready", "micro_live", "live"} else "WATCH",
                    code="MISSING_RUN_MANIFEST",
                    message="run_manifest.json is missing from the report evidence package.",
                    evidence={"stage": intended_stage},
                    recommendation="Write a run manifest tying config, cache, and data version to this report.",
                )
            )

        demo_data_used = bool(snapshot.assumptions.get("demo_data_used", False))
        audit_demo = bool(audit.get("demo_data_used", False)) if has_audit else False
        manifest_demo = _manifest_demo_data_used(manifest) if has_manifest else False
        demo_data_used = demo_data_used or audit_demo or manifest_demo
        if demo_data_used and intended_stage in {"micro_live_ready", "micro_live", "live"}:
            severity: Decision = "WATCH" if self.thresholds.allow_live_on_demo_data else "BLOCK"
            findings.append(
                ReviewFinding(
                    severity=severity,
                    code="DEMO_DATA_FOR_LIVE",
                    message="The report was produced with demo data and cannot justify live trading.",
                    evidence={
                        "summary_demo_data_used": bool(snapshot.assumptions.get("demo_data_used", False)),
                        "audit_demo_data_used": audit_demo,
                        "manifest_demo_data_used": manifest_demo,
                        "stage": intended_stage,
                    },
                    recommendation="Replace demo data with audited market data and rerun the review.",
                )
            )

        n_bars = int(snapshot.metric("n_bars"))
        if n_bars < self.thresholds.min_n_bars:
            findings.append(
                ReviewFinding(
                    severity="BLOCK" if intended_stage in {"micro_live_ready", "micro_live", "live"} else "WATCH",
                    code="SHORT_TEST_WINDOW",
                    message="The research window is too short to support release decisions.",
                    evidence={"n_bars": n_bars, "min_n_bars": self.thresholds.min_n_bars},
                    recommendation="Extend the backtest window and include out-of-sample periods.",
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
                    severity="BLOCK" if intended_stage in {"micro_live_ready", "micro_live", "live"} else "WATCH",
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
                "You may add critique, questions, and experiment ideas, but you may not "
                "upgrade BLOCK to WATCH/PASS or WATCH to PASS."
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
            "selected_candidate": payload.get("selected_candidate", payload.get("best_candidate", "")),
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
    summary["risk_notice"] = "Candidate experiment evidence is research/paper only and does not guarantee profit."
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
        "candidate_walk_forward_status": str(selected.get("status") or payload.get("status") or "UNKNOWN"),
        "candidate_walk_forward_window_count": int(selected.get("window_count", payload.get("window_count", 0)) or 0),
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


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


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
    if "demo_data_used" not in assumptions:
        items.append("Whether demo data or audited market data was used.")
    elif assumptions.get("demo_data_used"):
        items.append("A rerun on audited real market data.")
    if not snapshot.data_audit:
        items.append("data_audit.json proving the market data quality gate result.")
    if not snapshot.run_manifest:
        items.append("run_manifest.json tying the report to config, cache, and data version.")
    if any(finding.code == "CANDIDATE_WALK_FORWARD_METRICS_MISSING" for finding in findings):
        items.append("Candidate walk-forward tail-risk metrics for the selected candidate.")
    if snapshot.factor_ic_obs < 12:
        items.append("More RankIC observations across multiple rebalance periods.")
    if snapshot.order_count == 0:
        items.append("Paper-broker order logs proving the strategy can produce executable orders.")
    if not any(finding.code == "HIGH_TURNOVER" for finding in findings):
        items.append("A turnover stress test with higher transaction cost and slippage assumptions.")
    items.append("Parameter perturbation tests around holdings count, max weight, and rebalance cadence.")
    return _dedupe(items)


def _next_experiments(
    snapshot: ResearchSnapshot,
    findings: list[ReviewFinding],
    intended_stage: Stage,
) -> list[str]:
    del intended_stage
    finding_codes = {finding.code for finding in findings}
    experiments = [
        "Run an out-of-sample review and record validation windows in summary assumptions.",
        "Run a higher-cost stress test with doubled slippage and commission assumptions.",
        "Perturb n_holdings and max_weight to check whether performance survives small rule changes.",
    ]
    if snapshot.metric("max_drawdown") >= 0.10 or "DRAWDOWN_WATCH" in finding_codes:
        experiments.append("Stress-test drawdown by reducing gross exposure and comparing recovery time.")
    if snapshot.reject_rate > 0 or "ORDER_REJECT_WATCH" in finding_codes:
        experiments.append("Inspect rejected orders and rerun with smaller target weights or cash buffers.")
    if snapshot.avg_turnover_pct > 0.30 or "HIGH_TURNOVER" in finding_codes:
        experiments.append("Test lower rebalance frequency or turnover caps.")
    if snapshot.factor_ic_mean is None or snapshot.factor_ic_mean <= 0.02:
        experiments.append("Break down RankIC by factor to identify weak or inverted components.")
    if snapshot.assumptions.get("demo_data_used", False):
        experiments.append("Replace demo data with real cached A-share data before any promotion review.")
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
            "paper_trading",
            "small_manual_observation",
            "additional_out_of_sample_tests",
        ]
    if intended_stage == "live":
        return [
            "paper_trading",
            "micro_live_with_hard_risk_limits",
            "manual_approval_before_each_release",
        ]
    return ["paper_trading", "research_report_publication", "next_stage_review"]


def _prohibited_actions(decision: Decision, intended_stage: Stage) -> list[str]:
    actions = [
        "unattended_live_order_submission",
        "increase_capital_without_new_review",
        "override_risk_limits_by_llm_output",
    ]
    if decision in {"BLOCK", "WATCH"} or intended_stage in {"research", "paper", "micro_live_ready"}:
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
