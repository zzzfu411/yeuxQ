"""Research-only next experiments from blocked candidate evidence.

The report turns candidate selection, precheck, walk-forward, factor diagnostic,
and regime-validation artifacts into a practical follow-up queue. It is not a
promotion gate and never grants paper, live, or broker permissions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import csv
import json
from pathlib import Path
from typing import Any, Iterable


NEXT_EXPERIMENT_STATUS = "RESEARCH_ONLY"
PROMOTION_DECISION = "BLOCK"
DEFAULT_ALLOWED_ACTIONS = [
    "Run offline research experiments that collect more evidence for a blocked candidate.",
    "Attach this report to a human research note as a failure diagnosis and work queue.",
    "Use the recommendations to refine factors, turnover controls, cost stress, and regime tests.",
]
DEFAULT_PROHIBITED_ACTIONS = [
    "Do not treat any recommendation as paper approval, micro-live readiness, or a buy/sell signal.",
    "Do not connect this output to a real broker or generate broker order instructions.",
    "Do not use this output as --gate-report-dir for guarded candidate CLIs.",
    "Do not let LLM output upgrade this deterministic promotion decision.",
]
REQUIRED_PROMOTION_EVIDENCE = [
    "PASS source QA, guarded offline intake, data audit, and run manifest evidence.",
    "PASS candidate_experiment_readiness.json and candidate_experiment_launch.json.",
    "candidate_experiment_completion.json confirming every required artifact exists.",
    "Factor diagnostics and regime validation with no unresolved BLOCK.",
    "Paper-stage stability records and human approval before any micro-live readiness claim.",
]


@dataclass(frozen=True, slots=True)
class CandidateReportBundle:
    report_dir: str
    candidate_selection: dict[str, Any] = field(default_factory=dict)
    candidate_research_precheck: dict[str, Any] = field(default_factory=dict)
    candidate_walk_forward: dict[str, Any] = field(default_factory=dict)
    factor_diagnostics: dict[str, Any] = field(default_factory=dict)
    regime_validation: dict[str, Any] = field(default_factory=dict)
    stress_matrix: dict[str, Any] = field(default_factory=dict)

    def source_files(self) -> list[str]:
        files = []
        if self.candidate_selection:
            files.append("candidate_selection.json")
        if self.candidate_research_precheck:
            files.append("candidate_research_precheck.json")
        if self.candidate_walk_forward:
            files.append("candidate_walk_forward_report.json")
        if self.factor_diagnostics:
            files.append("candidate_factor_diagnostics.json")
        if self.regime_validation:
            files.append("candidate_regime_validation_report.json")
        if self.stress_matrix:
            files.append("candidate_stress_matrix.json")
        return files


@dataclass(frozen=True, slots=True)
class CandidateNextExperiment:
    priority: int
    candidate: str
    category: str
    trigger: str
    recommendation: str
    rationale: str
    evidence: list[str]
    command_hint: str
    allowed_stage: str = "research"
    status: str = "OPEN"
    can_enter_paper: bool = False
    can_enter_micro_live_ready: bool = False
    can_generate_broker_orders: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority": self.priority,
            "candidate": self.candidate,
            "category": self.category,
            "trigger": self.trigger,
            "recommendation": self.recommendation,
            "rationale": self.rationale,
            "evidence": self.evidence,
            "command_hint": self.command_hint,
            "allowed_stage": self.allowed_stage,
            "status": self.status,
            "can_enter_paper": self.can_enter_paper,
            "can_enter_micro_live_ready": self.can_enter_micro_live_ready,
            "can_generate_broker_orders": self.can_generate_broker_orders,
        }


@dataclass(frozen=True, slots=True)
class CandidateNextExperimentsReport:
    status: str
    promotion_decision: str
    report_dirs: list[str]
    source_files: list[str]
    candidate_count: int
    experiment_count: int
    experiments: list[CandidateNextExperiment]
    missing_evidence: list[str]
    allowed_actions: list[str]
    prohibited_actions: list[str]
    can_satisfy_launch_gate: bool = False
    can_enter_paper: bool = False
    can_enter_micro_live_ready: bool = False
    can_generate_broker_orders: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": "candidate_next_experiments",
            "status": self.status,
            "promotion_decision": self.promotion_decision,
            "report_dirs": self.report_dirs,
            "source_files": self.source_files,
            "candidate_count": self.candidate_count,
            "experiment_count": self.experiment_count,
            "experiments": [experiment.to_dict() for experiment in self.experiments],
            "missing_evidence": self.missing_evidence,
            "allowed_actions": self.allowed_actions,
            "prohibited_actions": self.prohibited_actions,
            "can_satisfy_launch_gate": self.can_satisfy_launch_gate,
            "can_enter_paper": self.can_enter_paper,
            "can_enter_micro_live_ready": self.can_enter_micro_live_ready,
            "can_generate_broker_orders": self.can_generate_broker_orders,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Candidate Next Experiments: {self.status}",
            "",
            f"- Promotion decision: `{self.promotion_decision}`",
            f"- Candidate count: {self.candidate_count}",
            f"- Experiment count: {self.experiment_count}",
            "",
            "This is a research-only failure diagnosis. It cannot satisfy a launch gate, enter paper, or generate broker orders.",
            "",
            "## Experiments",
        ]
        if not self.experiments:
            lines.append("- No experiments were generated; run candidate research precheck first.")
        for experiment in self.experiments:
            evidence = "; ".join(experiment.evidence) if experiment.evidence else "no evidence"
            lines.extend(
                [
                    "",
                    f"### {experiment.priority}. `{experiment.candidate}` - {experiment.category}",
                    "",
                    f"- Trigger: {experiment.trigger}",
                    f"- Recommendation: {experiment.recommendation}",
                    f"- Rationale: {experiment.rationale}",
                    f"- Evidence: {evidence}",
                    f"- Command hint: `{experiment.command_hint}`",
                    "- Allowed stage: `research`",
                ]
            )
        lines.extend(["", "## Missing Evidence"])
        lines.extend(f"- {item}" for item in self.missing_evidence)
        lines.extend(["", "## Allowed Actions"])
        lines.extend(f"- {item}" for item in self.allowed_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"

    def to_csv_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "priority": experiment.priority,
                "candidate": experiment.candidate,
                "category": experiment.category,
                "trigger": experiment.trigger,
                "recommendation": experiment.recommendation,
                "rationale": experiment.rationale,
                "evidence": " | ".join(experiment.evidence),
                "command_hint": experiment.command_hint,
                "allowed_stage": experiment.allowed_stage,
                "status": experiment.status,
                "can_enter_paper": experiment.can_enter_paper,
                "can_enter_micro_live_ready": experiment.can_enter_micro_live_ready,
                "can_generate_broker_orders": experiment.can_generate_broker_orders,
            }
            for experiment in self.experiments
        ]


@dataclass(slots=True)
class _CandidateContext:
    name: str
    selection_results: list[dict[str, Any]] = field(default_factory=list)
    walk_forward_summaries: list[dict[str, Any]] = field(default_factory=list)
    factor_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    regime_summaries: list[dict[str, Any]] = field(default_factory=list)
    stress_summaries: list[dict[str, Any]] = field(default_factory=list)
    stress_results: list[dict[str, Any]] = field(default_factory=list)
    source_dirs: list[str] = field(default_factory=list)


def load_candidate_report_bundle(report_dir: str | Path) -> CandidateReportBundle:
    root = Path(report_dir)
    return CandidateReportBundle(
        report_dir=str(root),
        candidate_selection=_read_json(root / "candidate_selection.json"),
        candidate_research_precheck=_read_json(root / "candidate_research_precheck.json"),
        candidate_walk_forward=_read_json(root / "candidate_walk_forward_report.json"),
        factor_diagnostics=_read_json(root / "candidate_factor_diagnostics.json"),
        regime_validation=_read_json(root / "candidate_regime_validation_report.json"),
        stress_matrix=_read_json(root / "candidate_stress_matrix.json"),
    )


def build_candidate_next_experiments_report(
    bundles: Iterable[CandidateReportBundle],
) -> CandidateNextExperimentsReport:
    bundle_list = list(bundles)
    contexts = _candidate_contexts(bundle_list)
    missing_evidence = _missing_evidence(bundle_list)
    experiments: list[CandidateNextExperiment] = []
    priority = 1

    if not contexts:
        experiments.append(
            CandidateNextExperiment(
                priority=priority,
                candidate="ALL",
                category="missing_candidate_evidence",
                trigger="No candidate_selection or candidate precheck evidence was found.",
                recommendation="Run a research-only candidate precheck before ranking or refining candidates.",
                rationale="Next experiments need blocked evidence to diagnose; absent evidence cannot support a candidate.",
                evidence=["No candidate report payloads contained candidate results."],
                command_hint=(
                    "python examples/run_candidate_research_precheck.py --config config/research_recent.yaml "
                    "--output-dir results/research_recent/<timestamp> --candidate <candidate>"
                ),
            )
        )
        priority += 1

    if _promotion_evidence_missing(missing_evidence):
        experiments.append(
            CandidateNextExperiment(
                priority=priority,
                candidate="ALL",
                category="data_and_gate_evidence",
                trigger="Promotion evidence is missing or incomplete.",
                recommendation=(
                    "Resolve source QA, guarded offline intake, data audit, run manifest, readiness, "
                    "launch, and completion evidence before treating research results as promotable."
                ),
                rationale="Strategy experiments cannot compensate for missing data provenance or launch gates.",
                evidence=_first_items(missing_evidence, limit=4),
                command_hint=(
                    "python examples/run_first_million_pipeline.py --config config/research_recent.yaml "
                    "--data-dir data_exports --output-dir results/first_million"
                ),
            )
        )
        priority += 1

    for name in sorted(contexts):
        context = contexts[name]
        for experiment in _candidate_experiments(context, starting_priority=priority):
            experiments.append(experiment)
            priority += 1

    report_dirs = [bundle.report_dir for bundle in bundle_list]
    source_files = sorted({file for bundle in bundle_list for file in bundle.source_files()})
    return CandidateNextExperimentsReport(
        status=NEXT_EXPERIMENT_STATUS,
        promotion_decision=PROMOTION_DECISION,
        report_dirs=report_dirs,
        source_files=source_files,
        candidate_count=len(contexts),
        experiment_count=len(experiments),
        experiments=experiments,
        missing_evidence=missing_evidence or list(REQUIRED_PROMOTION_EVIDENCE),
        allowed_actions=list(DEFAULT_ALLOWED_ACTIONS),
        prohibited_actions=list(DEFAULT_PROHIBITED_ACTIONS),
    )


def write_candidate_next_experiments_report(
    report: CandidateNextExperimentsReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "candidate_next_experiments.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "candidate_next_experiments.md").write_text(report.to_markdown(), encoding="utf-8")
    _write_csv(root / "candidate_next_experiments.csv", report.to_csv_rows())
    return root


def _candidate_contexts(bundles: list[CandidateReportBundle]) -> dict[str, _CandidateContext]:
    contexts: dict[str, _CandidateContext] = {}
    for bundle in bundles:
        for name in _precheck_candidates(bundle.candidate_research_precheck):
            _context(contexts, name).source_dirs.append(bundle.report_dir)
        for result in bundle.candidate_selection.get("results", []) or []:
            if not isinstance(result, dict):
                continue
            name = str(result.get("name", "") or "")
            if not name:
                continue
            ctx = _context(contexts, name)
            ctx.selection_results.append(result)
            ctx.source_dirs.append(bundle.report_dir)
        for summary in bundle.candidate_walk_forward.get("summaries", []) or []:
            if not isinstance(summary, dict):
                continue
            name = str(summary.get("candidate", "") or "")
            if name:
                _context(contexts, name).walk_forward_summaries.append(summary)
        for diagnostic in bundle.factor_diagnostics.get("diagnostics", []) or []:
            if not isinstance(diagnostic, dict):
                continue
            name = str(diagnostic.get("candidate", "") or "")
            if name:
                _context(contexts, name).factor_diagnostics.append(diagnostic)
        for summary in bundle.regime_validation.get("summaries", []) or []:
            if not isinstance(summary, dict):
                continue
            name = str(summary.get("candidate", "") or "")
            if name:
                _context(contexts, name).regime_summaries.append(summary)
        for summary in bundle.stress_matrix.get("summaries", []) or []:
            if not isinstance(summary, dict):
                continue
            name = str(summary.get("candidate", "") or "")
            if name:
                _context(contexts, name).stress_summaries.append(summary)
        for result in bundle.stress_matrix.get("results", []) or []:
            if not isinstance(result, dict):
                continue
            name = str(result.get("candidate", "") or "")
            if name:
                _context(contexts, name).stress_results.append(result)
    return contexts


def _candidate_experiments(
    context: _CandidateContext,
    *,
    starting_priority: int,
) -> list[CandidateNextExperiment]:
    experiments: list[CandidateNextExperiment] = []
    priority = starting_priority
    name = context.name
    latest = context.selection_results[-1] if context.selection_results else {}
    wf = context.walk_forward_summaries[-1] if context.walk_forward_summaries else {}

    if _selection_decisions(context):
        blocked = [decision for decision in _selection_decisions(context) if decision == "BLOCK"]
        if blocked:
            experiments.append(
                _experiment(
                    priority,
                    name,
                    "blocked_candidate_review",
                    "Candidate selection decision is BLOCK.",
                    "Keep the candidate in research and diagnose the first failing gate before adding complexity.",
                    "A blocked score means the current evidence is insufficient even if a rank is available.",
                    _candidate_evidence(context),
                    "python examples/run_candidate_research_precheck.py --config config/research_recent.yaml "
                    "--output-dir results/research_recent/<timestamp> --candidate "
                    f"{name}",
                )
            )
            priority += 1

    for experiment in _candidate_specific_experiments(context, starting_priority=priority):
        experiments.append(experiment)
        priority += 1
    for experiment in _stress_pass_variant_experiments(context, starting_priority=priority):
        experiments.append(experiment)
        priority += 1

    annual_return = _min_selection_metric(context, "annualized_return")
    if annual_return is not None and annual_return <= 0.0:
        experiments.append(
            _experiment(
                priority,
                name,
                "adverse_window_review",
                f"Latest selection annualized return is {annual_return:.2%}.",
                "Run adverse-window attribution and compare failed holdings, factor scores, and rebalance dates.",
                "A negative recent selection window cannot support a stable compounding claim.",
                [f"annualized_return={annual_return:.2%}", *_candidate_evidence(context)],
                "python examples/run_candidate_walk_forward.py --config config/research_recent.yaml "
                f"--output-dir results/research_recent/<timestamp> --candidate {name}",
            )
        )
        priority += 1

    worst_return = _min_walk_forward_value(context, "worst_total_return")
    positive_ratio = _min_walk_forward_value(context, "positive_return_ratio")
    if worst_return is not None and worst_return < 0.0:
        experiments.append(
            _experiment(
                priority,
                name,
                "walk_forward_failure_analysis",
                f"Worst walk-forward return is {worst_return:.2%}.",
                "Rerun the failed windows with factor attribution, cost stress, and rebalance-date notes.",
                "A strategy that loses in forward windows needs falsification before parameter changes.",
                [f"worst_total_return={worst_return:.2%}", *_walk_forward_evidence(wf)],
                "python examples/run_candidate_research_precheck.py --config config/research_recent.yaml "
                f"--output-dir results/research_recent/<timestamp> --candidate {name} "
                "--include-factor-diagnostics --include-regime-validation",
            )
        )
        priority += 1
    if positive_ratio is not None and positive_ratio < 0.60:
        experiments.append(
            _experiment(
                priority,
                name,
                "positive_window_ratio",
                f"Positive forward-window ratio is {positive_ratio:.2%}.",
                "Expand the walk-forward sample and require a stable majority of positive windows.",
                "A low positive-window ratio points to timing dependence instead of robust compounding.",
                [f"positive_return_ratio={positive_ratio:.2%}", *_walk_forward_evidence(wf)],
                "python examples/run_candidate_research_precheck.py --config config/research_recent.yaml "
                f"--output-dir results/research_recent/<timestamp> --candidate {name} --max-windows 0",
            )
        )
        priority += 1

    turnover = _max_selection_metric(context, "avg_turnover_pct")
    if turnover is not None and turnover >= 0.80:
        experiments.append(
            _experiment(
                priority,
                name,
                "turnover_control",
                f"Average turnover is {turnover:.2%}.",
                "Test lower rebalance frequency, wider holdings, stricter max weight, target-drift thresholds, per-rebalance new-position caps, and score smoothing.",
                "High turnover can consume the return path for a small A-share account after costs and rejects.",
                [f"avg_turnover_pct={turnover:.2%}", *_candidate_evidence(context)],
                "python examples/run_candidate_research_stress_matrix.py --config config/research_recent.yaml "
                f"--output-dir results/research_recent/<timestamp> --candidate {name} "
                "--scenario baseline --scenario turnover_control --scenario stability_control --scenario score_smoothing",
            )
        )
        priority += 1

    turnover_ablation = _turnover_control_ablation_experiment(context, priority)
    if turnover_ablation:
        experiments.append(turnover_ablation)
        priority += 1

    stability_ablation = _stability_control_ablation_experiment(context, priority)
    if stability_ablation:
        experiments.append(stability_ablation)
        priority += 1

    smoothing_ablation = _score_smoothing_ablation_experiment(context, priority)
    if smoothing_ablation:
        experiments.append(smoothing_ablation)
        priority += 1

    reject_rate = _max_selection_metric(context, "reject_rate")
    if reject_rate is not None and reject_rate >= 0.20:
        experiments.append(
            _experiment(
                priority,
                name,
                "execution_rejects",
                f"Reject rate is {reject_rate:.2%}.",
                "Diagnose rejects by price-limit, suspension, lot size, cash, and liquidity reason.",
                "Rejected orders can hide untradeable performance and must be explained before paper planning.",
                [f"reject_rate={reject_rate:.2%}", *_candidate_evidence(context)],
                "python examples/run_candidate_research_precheck.py --config config/research_recent.yaml "
                f"--output-dir results/research_recent/<timestamp> --candidate {name}",
            )
        )
        priority += 1

    if context.stress_summaries:
        stress = context.stress_summaries[-1]
        if str(stress.get("status", "")).upper() != "PASS":
            experiments.append(
                _experiment(
                    priority,
                    name,
                    "stress_matrix_failure",
                    f"Candidate stress matrix status is {stress.get('status', 'UNKNOWN')}.",
                    "Use the least-bad stress variant only as a new research hypothesis; do not promote the current candidate.",
                    "Parameter and cost stress did not produce stable evidence, so the failure is structural rather than a single setting.",
                    _stress_evidence(stress),
                    "python examples/run_candidate_research_stress_matrix.py --config config/research_recent.yaml "
                    f"--output-dir results/research_recent/<timestamp> --candidate {name}",
                )
            )
            priority += 1

    drawdown = _max_selection_metric(context, "max_drawdown")
    worst_drawdown = _max_walk_forward_value(context, "worst_max_drawdown")
    drawdown_evidence = max(value for value in [drawdown, worst_drawdown] if value is not None) if (
        drawdown is not None or worst_drawdown is not None
    ) else None
    if drawdown_evidence is not None and drawdown_evidence >= 0.15:
        experiments.append(
            _experiment(
                priority,
                name,
                "drawdown_budget",
                f"Drawdown evidence reached {drawdown_evidence:.2%}.",
                "Run drawdown-path attribution and test exposure caps before any return-seeking tweak.",
                "The first-million path needs survivability; drawdown pressure has priority over headline return.",
                [f"drawdown={drawdown_evidence:.2%}", *_candidate_evidence(context)],
                "python examples/run_candidate_research_stress_matrix.py --config config/research_recent.yaml "
                f"--output-dir results/research_recent/<timestamp> --candidate {name}",
            )
        )
        priority += 1

    sharpe = _min_selection_metric(context, "sharpe_ratio")
    if sharpe is not None and sharpe < 0.80:
        experiments.append(
            _experiment(
                priority,
                name,
                "weak_risk_adjusted_return",
                f"Sharpe ratio is {sharpe:.2f}.",
                "Compare factor ablation and cost stress to see whether the signal survives risk adjustment.",
                "Weak risk-adjusted return is a warning that raw returns may be timing or exposure artifacts.",
                [f"sharpe_ratio={sharpe:.2f}", *_candidate_evidence(context)],
                "python examples/run_candidate_research_precheck.py --config config/research_recent.yaml "
                f"--output-dir results/research_recent/<timestamp> --candidate {name} "
                "--include-factor-diagnostics",
            )
        )
        priority += 1

    return_margin = _min_capital_goal_metric(context, "return_margin")
    if return_margin is not None and return_margin < 0.0:
        experiments.append(
            _experiment(
                priority,
                name,
                "capital_goal_fit",
                f"Capital-goal return margin is {return_margin:.2%}.",
                "Reject the one-million compounding claim until out-of-sample return margin is positive after costs.",
                "The capital goal is a feasibility screen, not an optimism setting.",
                [f"capital_goal_return_margin={return_margin:.2%}", *_capital_goal_findings(latest)],
                "python examples/run_candidate_selection.py --config config/research_recent.yaml "
                f"--output-dir results/research_recent/<timestamp> --candidate {name} "
                "--starting-capital 100000 --target-capital 1000000 --years 8",
            )
        )
        priority += 1

    trend_days = _max_trend_filter_days(context)
    if _is_trend_candidate(context) and trend_days > 0:
        experiments.append(
            _experiment(
                priority,
                name,
                "trend_filter_ablation",
                f"Trend filter was active for {trend_days} day(s).",
                "Compare filtered versus unfiltered windows and measure cash drag, exposure scale, and missed rebound.",
                "A trend filter only helps if lower drawdown is not just hidden cash drag.",
                [f"trend_filter_active_days={trend_days}", *_walk_forward_evidence(wf)],
                "python examples/run_candidate_research_precheck.py --config config/research_recent.yaml "
                f"--output-dir results/research_recent/<timestamp> --candidate {name}",
            )
        )
        priority += 1

    if not context.factor_diagnostics:
        experiments.append(
            _experiment(
                priority,
                name,
                "missing_factor_diagnostics",
                "candidate_factor_diagnostics.json is missing for this candidate.",
                "Run component diagnostics before trusting a composite candidate ranking.",
                "Without ablation evidence, one lucky factor can masquerade as a robust strategy.",
                ["factor_diagnostics=missing"],
                "python examples/run_candidate_research_precheck.py --config config/research_recent.yaml "
                f"--output-dir results/research_recent/<timestamp> --candidate {name} "
                "--include-factor-diagnostics",
            )
        )
        priority += 1
    else:
        diagnostic = context.factor_diagnostics[-1]
        if str(diagnostic.get("status", "")).upper() != "PASS":
            experiments.append(
                _experiment(
                    priority,
                    name,
                    "factor_dependency",
                    f"Factor diagnostics status is {diagnostic.get('status', 'UNKNOWN')}.",
                    "Rerun factor ablation and reject candidates dominated by one component.",
                    "Component concentration is a common overfit path in multi-factor research.",
                    _factor_evidence(diagnostic),
                    "python examples/run_candidate_research_precheck.py --config config/research_recent.yaml "
                    f"--output-dir results/research_recent/<timestamp> --candidate {name} "
                    "--include-factor-diagnostics",
                )
            )
            priority += 1

    if not context.regime_summaries:
        experiments.append(
            _experiment(
                priority,
                name,
                "missing_regime_validation",
                "candidate_regime_validation_report.json is missing for this candidate.",
                "Run regime-stratified validation before comparing candidates for current A-share conditions.",
                "A candidate that only works in one regime is not ready for a stable compounding workflow.",
                ["regime_validation=missing"],
                "python examples/run_candidate_research_precheck.py --config config/research_recent.yaml "
                f"--output-dir results/research_recent/<timestamp> --candidate {name} "
                "--include-regime-validation",
            )
        )
        priority += 1
    else:
        regime = context.regime_summaries[-1]
        if str(regime.get("status", "")).upper() != "PASS":
            experiments.append(
                _experiment(
                    priority,
                    name,
                    "regime_failure",
                    f"Regime validation status is {regime.get('status', 'UNKNOWN')}.",
                    "Inspect adverse and defensive buckets and require no candidate-level BLOCK buckets.",
                    "Stable A-share daily strategies need evidence across market states, not just a headline sample.",
                    _regime_evidence(regime),
                    "python examples/run_candidate_research_precheck.py --config config/research_recent.yaml "
                    f"--output-dir results/research_recent/<timestamp> --candidate {name} "
                    "--include-regime-validation",
                )
            )
            priority += 1
    return experiments


def _candidate_specific_experiments(
    context: _CandidateContext,
    *,
    starting_priority: int,
) -> list[CandidateNextExperiment]:
    experiments: list[CandidateNextExperiment] = []
    priority = starting_priority
    stress = context.stress_summaries[-1] if context.stress_summaries else {}
    walk_forward = context.walk_forward_summaries[-1] if context.walk_forward_summaries else {}

    if context.name == "low_turnover_low_concentration_price_volume":
        evidence = [
            *_candidate_evidence(context),
            *_walk_forward_evidence(walk_forward),
            *_stress_evidence(stress),
        ]
        experiments.append(
            _experiment(
                priority,
                context.name,
                "low_concentration_vs_baseline",
                "Candidate is the lower-concentration quarterly variant of low_turnover_price_volume.",
                (
                    "Compare this variant directly against low_turnover_price_volume across all "
                    "windows and keep it only if the lower max weight improves drawdown or "
                    "Sharpe without erasing return margin."
                ),
                (
                    "This candidate exists to test concentration relief, so it needs a "
                    "head-to-head baseline comparison instead of another isolated tweak."
                ),
                evidence,
                (
                    "python examples/run_candidate_research_precheck.py --config "
                    "config/research_recent.yaml --output-dir results/research_recent/<timestamp> "
                    "--candidate low_turnover_price_volume "
                    "--candidate low_turnover_low_concentration_price_volume "
                    "--max-windows 0 --full-sample-selection "
                    "--include-factor-diagnostics --include-regime-validation"
                ),
            )
        )
        priority += 1

    if context.name == "trend_filtered_quarterly_price_volume":
        trend_days = _max_trend_filter_days(context)
        evidence = [
            f"trend_filter_active_days={trend_days}",
            *_candidate_evidence(context),
            *_walk_forward_evidence(walk_forward),
            *_stress_evidence(stress),
        ]
        experiments.append(
            _experiment(
                priority,
                context.name,
                "quarterly_trend_vs_baseline",
                "Candidate is the quarterly cadence variant of trend_filtered_price_volume.",
                (
                    "Compare trend_filtered_price_volume versus this quarterly cadence "
                    "across all windows and require the quarterly path to improve Sharpe "
                    "or return margin without hiding cash drag or missed rebounds."
                ),
                (
                    "This candidate exists to test cadence, so it needs a direct "
                    "monthly-versus-quarterly comparison before any new filter tuning."
                ),
                evidence,
                (
                    "python examples/run_candidate_research_precheck.py --config "
                    "config/research_recent.yaml --output-dir results/research_recent/<timestamp> "
                    "--candidate trend_filtered_price_volume "
                    "--candidate trend_filtered_quarterly_price_volume "
                    "--max-windows 0 --full-sample-selection "
                    "--include-factor-diagnostics --include-regime-validation"
                ),
            )
        )

    if context.name == "liquidity_neutral_momentum_guard_price_volume":
        evidence = [
            "lineage=stable_universe_slow_signal_price_volume->long_momentum_liquidity_monthly_price_volume->liquidity_neutral_momentum_guard_price_volume",
            *_candidate_evidence(context),
            *_walk_forward_evidence(walk_forward),
            *_stress_evidence(stress),
        ]
        experiments.append(
            _experiment(
                priority,
                context.name,
                "liquidity_neutral_guard_lineage_review",
                "Liquidity-neutral guarded candidate remains blocked after reducing drawdown pressure.",
                (
                    "Run a three-candidate lineage review before adding another factor: compare "
                    "stable_universe_slow_signal_price_volume, long_momentum_liquidity_monthly_price_volume, "
                    "and liquidity_neutral_momentum_guard_price_volume on identical windows."
                ),
                (
                    "This isolates whether the failure came from liquidity dependency, the defensive guard, "
                    "quarterly cadence, or unstable slow-signal construction instead of widening the search space."
                ),
                evidence,
                (
                    "python examples/run_candidate_research_precheck.py --config "
                    "config/research_recent.yaml --output-dir results/research_recent/<timestamp> "
                    "--candidate stable_universe_slow_signal_price_volume "
                    "--candidate long_momentum_liquidity_monthly_price_volume "
                    "--candidate liquidity_neutral_momentum_guard_price_volume "
                    "--max-windows 0 --full-sample-selection "
                    "--include-factor-diagnostics --include-regime-validation"
                ),
            )
        )

    return experiments


def _stress_pass_variant_experiments(
    context: _CandidateContext,
    *,
    starting_priority: int,
) -> list[CandidateNextExperiment]:
    suggested = _lower_concentration_variant_candidate(context.name)
    if not suggested:
        return []
    lower_pass = [
        result
        for result in context.stress_results
        if str(result.get("scenario") or "") == "lower_concentration"
        and str(result.get("status") or "").upper() == "PASS"
    ]
    if not lower_pass:
        return []
    result = lower_pass[-1]
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    evidence = [
        "lower_concentration_status=PASS",
        f"total_return={_as_float(metrics.get('total_return')):.2%}",
        f"annualized_return={_as_float(metrics.get('annualized_return')):.2%}",
        f"max_drawdown={_as_float(metrics.get('max_drawdown')):.2%}",
        f"sharpe_ratio={_as_float(metrics.get('sharpe_ratio')):.2f}",
        f"avg_turnover_pct={_as_float(result.get('avg_turnover_pct')):.2%}",
        f"reject_rate={_as_float(result.get('reject_rate')):.2%}",
    ]
    parameters = result.get("parameters") if isinstance(result.get("parameters"), dict) else {}
    if parameters:
        evidence.extend(
            [
                f"n_holdings={parameters.get('n_holdings', '')}",
                f"max_weight={_as_float(parameters.get('max_weight')):.2%}",
                f"rebalance={parameters.get('rebalance', '')}",
            ]
        )
    return [
        _experiment(
            starting_priority,
            context.name,
            "stress_pass_variant_candidate",
            f"Stress scenario lower_concentration reached PASS for {context.name}.",
            (
                f"Register and rerun `{suggested}` as the next research-only candidate, "
                "then compare it head-to-head against the original candidate."
            ),
            (
                "A PASS stress scenario is not promotion evidence, but it is a useful pre-registered "
                "variant to retest for lower drawdown, lower turnover, and compounding discipline."
            ),
            evidence,
            (
                "python examples/run_candidate_research_precheck.py --config "
                "config/research_recent.yaml --output-dir results/research_recent/<timestamp> "
                f"--candidate {context.name} --candidate {suggested} --max-windows 0 "
                "--full-sample-selection --include-factor-diagnostics --include-regime-validation"
            ),
        )
    ]


def _turnover_control_ablation_experiment(
    context: _CandidateContext,
    priority: int,
) -> CandidateNextExperiment | None:
    baseline = _latest_stress_result(context, "baseline")
    controlled = _latest_stress_result(context, "turnover_control")
    if not baseline or not controlled:
        return None
    baseline_turnover = _as_float(baseline.get("avg_turnover_pct"))
    controlled_turnover = _as_float(controlled.get("avg_turnover_pct"))
    baseline_maintenance = _as_float(baseline.get("avg_maintenance_turnover_pct"))
    controlled_maintenance = _as_float(controlled.get("avg_maintenance_turnover_pct"))
    improvement = baseline_turnover - controlled_turnover
    maintenance_improvement = baseline_maintenance - controlled_maintenance
    if improvement >= 0.05 and controlled_turnover < baseline_turnover * 0.95:
        return None
    if (
        baseline_maintenance > 0
        and maintenance_improvement >= 0.05
        and controlled_maintenance < baseline_maintenance * 0.95
    ):
        return None
    baseline_metrics = baseline.get("metrics") if isinstance(baseline.get("metrics"), dict) else {}
    controlled_metrics = controlled.get("metrics") if isinstance(controlled.get("metrics"), dict) else {}
    evidence = [
        f"baseline_turnover={baseline_turnover:.2%}",
        f"turnover_control_turnover={controlled_turnover:.2%}",
        f"turnover_improvement={improvement:.2%}",
        f"baseline_maintenance_turnover={baseline_maintenance:.2%}",
        f"turnover_control_maintenance_turnover={controlled_maintenance:.2%}",
        f"maintenance_turnover_improvement={maintenance_improvement:.2%}",
        f"baseline_total_return={_as_float(baseline_metrics.get('total_return')):.2%}",
        f"turnover_control_total_return={_as_float(controlled_metrics.get('total_return')):.2%}",
        f"baseline_max_drawdown={_as_float(baseline_metrics.get('max_drawdown')):.2%}",
        f"turnover_control_max_drawdown={_as_float(controlled_metrics.get('max_drawdown')):.2%}",
    ]
    parameters = controlled.get("parameters") if isinstance(controlled.get("parameters"), dict) else {}
    if parameters:
        evidence.extend(
            [
                f"hold_rank_buffer={parameters.get('hold_rank_buffer', 0)}",
                f"min_trade_weight={_as_float(parameters.get('min_trade_weight')):.2%}",
            ]
        )
    return _experiment(
        priority,
        context.name,
        "turnover_control_ablation_failed",
        "Turnover-control stress did not materially reduce turnover versus baseline.",
        (
            "Do not promote the hold-rank-buffer/min-trade-threshold variant; "
            "test more structural low-turnover ideas instead."
        ),
        (
            "A target-drift band only helps if it changes realized orders. If turnover remains high, "
            "the candidate needs a per-rebalance new-position cap, signal smoothing, a more stable universe, or a slower/rebalanced design."
        ),
        evidence,
        "python examples/run_candidate_research_stress_matrix.py --config config/research_recent.yaml "
        f"--output-dir results/research_recent/<timestamp> --candidate {context.name} "
        "--scenario stability_control --scenario score_smoothing --scenario wider_basket --scenario lower_concentration --scenario rebalance_alt",
    )


def _stability_control_ablation_experiment(
    context: _CandidateContext,
    priority: int,
) -> CandidateNextExperiment | None:
    baseline = _latest_stress_result(context, "baseline")
    controlled = _latest_stress_result(context, "stability_control")
    if not baseline or not controlled:
        return None
    baseline_turnover = _as_float(baseline.get("avg_turnover_pct"))
    controlled_turnover = _as_float(controlled.get("avg_turnover_pct"))
    baseline_maintenance = _as_float(baseline.get("avg_maintenance_turnover_pct"))
    controlled_maintenance = _as_float(controlled.get("avg_maintenance_turnover_pct"))
    improvement = baseline_turnover - controlled_turnover
    maintenance_improvement = baseline_maintenance - controlled_maintenance
    if improvement >= 0.05 and controlled_turnover < baseline_turnover * 0.95:
        return None
    if (
        baseline_maintenance > 0
        and maintenance_improvement >= 0.05
        and controlled_maintenance < baseline_maintenance * 0.95
    ):
        return None
    parameters = controlled.get("parameters") if isinstance(controlled.get("parameters"), dict) else {}
    evidence = [
        f"baseline_turnover={baseline_turnover:.2%}",
        f"stability_control_turnover={controlled_turnover:.2%}",
        f"turnover_improvement={improvement:.2%}",
        f"baseline_maintenance_turnover={baseline_maintenance:.2%}",
        f"stability_control_maintenance_turnover={controlled_maintenance:.2%}",
        f"maintenance_turnover_improvement={maintenance_improvement:.2%}",
        f"max_new_positions={parameters.get('max_new_positions', 0)}",
        f"min_trade_weight={_as_float(parameters.get('min_trade_weight')):.2%}",
        f"hold_rank_buffer={parameters.get('hold_rank_buffer', 0)}",
    ]
    return _experiment(
        priority,
        context.name,
        "stability_control_ablation_failed",
        "Stronger stability-control stress did not materially reduce turnover versus baseline.",
        (
            "Do not promote the hold-buffer/drift-band/new-position-cap variant; "
            "move to signal smoothing, stable-universe design, or slower signal definitions."
        ),
        (
            "If a per-rebalance new-position cap still leaves realized orders unchanged, "
            "the high turnover is likely coming from the candidate's score path or universe churn."
        ),
        evidence,
        "python examples/run_candidate_research_stress_matrix.py --config config/research_recent.yaml "
        f"--output-dir results/research_recent/<timestamp> --candidate {context.name} "
        "--scenario baseline --scenario score_smoothing",
    )


def _score_smoothing_ablation_experiment(
    context: _CandidateContext,
    priority: int,
) -> CandidateNextExperiment | None:
    baseline = _latest_stress_result(context, "baseline")
    controlled = _latest_stress_result(context, "score_smoothing")
    if not baseline or not controlled:
        return None
    baseline_turnover = _as_float(baseline.get("avg_turnover_pct"))
    controlled_turnover = _as_float(controlled.get("avg_turnover_pct"))
    baseline_maintenance = _as_float(baseline.get("avg_maintenance_turnover_pct"))
    controlled_maintenance = _as_float(controlled.get("avg_maintenance_turnover_pct"))
    improvement = baseline_turnover - controlled_turnover
    maintenance_improvement = baseline_maintenance - controlled_maintenance
    if improvement >= 0.05 and controlled_turnover < baseline_turnover * 0.95:
        return None
    if (
        baseline_maintenance > 0
        and maintenance_improvement >= 0.05
        and controlled_maintenance < baseline_maintenance * 0.95
    ):
        return None
    parameters = controlled.get("parameters") if isinstance(controlled.get("parameters"), dict) else {}
    evidence = [
        f"baseline_turnover={baseline_turnover:.2%}",
        f"score_smoothing_turnover={controlled_turnover:.2%}",
        f"turnover_improvement={improvement:.2%}",
        f"baseline_maintenance_turnover={baseline_maintenance:.2%}",
        f"score_smoothing_maintenance_turnover={controlled_maintenance:.2%}",
        f"maintenance_turnover_improvement={maintenance_improvement:.2%}",
        f"score_smoothing_observations={parameters.get('score_smoothing_observations', 0)}",
        f"score_smoothing_step_days={parameters.get('score_smoothing_step_days', 0)}",
    ]
    return _experiment(
        priority,
        context.name,
        "score_smoothing_ablation_failed",
        "Score-smoothing stress did not materially reduce turnover versus baseline.",
        (
            "Do not promote the smoothed-score variant; move to stable-universe design, "
            "slower raw signals, or a new lower-turnover candidate."
        ),
        (
            "If past-only score smoothing does not change realized orders, the current candidate "
            "likely needs a different factor definition or universe construction rather than another trading threshold."
        ),
        evidence,
        "python examples/run_candidate_research_precheck.py --config config/research_recent.yaml "
        f"--output-dir results/research_recent/<timestamp> --candidate {context.name} "
        "--candidate stable_universe_slow_signal_price_volume --max-windows 0 "
        "--full-sample-selection --include-factor-diagnostics --include-regime-validation",
    )


def _latest_stress_result(
    context: _CandidateContext,
    scenario: str,
) -> dict[str, Any]:
    matches = [
        result
        for result in context.stress_results
        if str(result.get("scenario", "")).strip() == scenario
    ]
    return matches[-1] if matches else {}


def _lower_concentration_variant_candidate(candidate: str) -> str:
    mapping = {
        "trend_filtered_quarterly_price_volume": (
            "trend_filtered_quarterly_low_concentration_price_volume"
        ),
    }
    return mapping.get(candidate, "")


def _experiment(
    priority: int,
    candidate: str,
    category: str,
    trigger: str,
    recommendation: str,
    rationale: str,
    evidence: list[str],
    command_hint: str,
) -> CandidateNextExperiment:
    return CandidateNextExperiment(
        priority=priority,
        candidate=candidate,
        category=category,
        trigger=trigger,
        recommendation=recommendation,
        rationale=rationale,
        evidence=_first_items(evidence, limit=8),
        command_hint=command_hint,
    )


def _context(contexts: dict[str, _CandidateContext], name: str) -> _CandidateContext:
    if name not in contexts:
        contexts[name] = _CandidateContext(name=name)
    return contexts[name]


def _precheck_candidates(payload: dict[str, Any]) -> list[str]:
    return [str(name) for name in payload.get("candidates", []) or [] if name]


def _missing_evidence(bundles: list[CandidateReportBundle]) -> list[str]:
    missing: list[str] = []
    if not bundles:
        return list(REQUIRED_PROMOTION_EVIDENCE)
    for bundle in bundles:
        missing.extend(
            str(item)
            for item in bundle.candidate_research_precheck.get("missing_promotion_evidence", []) or []
            if item
        )
        if not bundle.candidate_selection:
            missing.append(f"{bundle.report_dir}: candidate_selection.json is missing.")
        if not bundle.candidate_walk_forward:
            missing.append(f"{bundle.report_dir}: candidate_walk_forward_report.json is missing.")
        if not bundle.factor_diagnostics:
            missing.append(f"{bundle.report_dir}: candidate_factor_diagnostics.json is missing.")
        if not bundle.regime_validation:
            missing.append(
                f"{bundle.report_dir}: candidate_regime_validation_report.json is missing."
            )
        if not bundle.stress_matrix:
            missing.append(f"{bundle.report_dir}: candidate_stress_matrix.json is missing.")
    return _unique([*missing, *REQUIRED_PROMOTION_EVIDENCE])


def _promotion_evidence_missing(items: list[str]) -> bool:
    text = "\n".join(items).lower()
    markers = ["source qa", "offline intake", "launch", "completion", "paper-stage", "missing"]
    return any(marker in text for marker in markers)


def _candidate_evidence(context: _CandidateContext) -> list[str]:
    latest = context.selection_results[-1] if context.selection_results else {}
    score = latest.get("score", {}) if isinstance(latest.get("score"), dict) else {}
    evidence = []
    if latest:
        evidence.append(f"decision={score.get('decision', latest.get('decision', 'UNKNOWN'))}")
        for key in ["annualized_return", "max_drawdown", "sharpe_ratio"]:
            value = _metric(latest, key)
            if value is not None:
                evidence.append(f"{key}={_format_metric(key, value)}")
        if "avg_turnover_pct" in latest:
            evidence.append(f"avg_turnover_pct={_as_float(latest.get('avg_turnover_pct')):.2%}")
        if "avg_maintenance_turnover_pct" in latest:
            evidence.append(
                f"avg_maintenance_turnover_pct={_as_float(latest.get('avg_maintenance_turnover_pct')):.2%}"
            )
        if "reject_rate" in latest:
            evidence.append(f"reject_rate={_as_float(latest.get('reject_rate')):.2%}")
    return evidence


def _walk_forward_evidence(summary: dict[str, Any]) -> list[str]:
    if not summary:
        return []
    return [
        f"walk_forward_status={summary.get('status', 'UNKNOWN')}",
        f"window_count={summary.get('window_count', 0)}",
        f"positive_return_ratio={_as_float(summary.get('positive_return_ratio')):.2%}",
        f"worst_total_return={_as_float(summary.get('worst_total_return')):.2%}",
        f"worst_max_drawdown={_as_float(summary.get('worst_max_drawdown')):.2%}",
    ]


def _factor_evidence(diagnostic: dict[str, Any]) -> list[str]:
    return [
        f"factor_status={diagnostic.get('status', 'UNKNOWN')}",
        f"component_count={diagnostic.get('component_count', 0)}",
        f"component_pass_count={diagnostic.get('component_pass_count', 0)}",
        f"dependency_ratio={_as_float(diagnostic.get('dependency_ratio')):.2f}",
        *_first_items([str(item) for item in diagnostic.get("findings", []) or []], limit=3),
    ]


def _regime_evidence(summary: dict[str, Any]) -> list[str]:
    return [
        f"regime_status={summary.get('status', 'UNKNOWN')}",
        f"known_regime_count={summary.get('known_regime_count', 0)}",
        f"adverse_regime_window_count={summary.get('adverse_regime_window_count', 0)}",
        f"block_bucket_count={summary.get('block_bucket_count', 0)}",
        *_first_items([str(item) for item in summary.get("notes", []) or []], limit=3),
    ]


def _stress_evidence(summary: dict[str, Any]) -> list[str]:
    return [
        f"stress_status={summary.get('status', 'UNKNOWN')}",
        f"scenario_count={summary.get('scenario_count', 0)}",
        f"pass_count={summary.get('pass_count', 0)}",
        f"watch_count={summary.get('watch_count', 0)}",
        f"block_count={summary.get('block_count', 0)}",
        f"worst_total_return={_as_float(summary.get('worst_total_return')):.2%}",
        f"worst_max_drawdown={_as_float(summary.get('worst_max_drawdown')):.2%}",
        f"max_turnover_pct={_as_float(summary.get('max_turnover_pct')):.2%}",
        f"max_maintenance_turnover_pct={_as_float(summary.get('max_maintenance_turnover_pct')):.2%}",
        *_first_items([str(item) for item in summary.get("findings", []) or []], limit=3),
    ]


def _capital_goal_findings(result: dict[str, Any]) -> list[str]:
    review = result.get("capital_goal_fit_review", {})
    if not isinstance(review, dict):
        return []
    return [str(item) for item in review.get("findings", []) or [] if item][:4]


def _selection_decisions(context: _CandidateContext) -> list[str]:
    decisions = []
    for result in context.selection_results:
        score = result.get("score", {}) if isinstance(result.get("score"), dict) else {}
        decision = str(score.get("decision", result.get("decision", "")) or "").upper()
        if decision:
            decisions.append(decision)
    return decisions


def _min_selection_metric(context: _CandidateContext, key: str) -> float | None:
    values = [_metric(result, key) for result in context.selection_results]
    clean = [value for value in values if value is not None]
    return min(clean) if clean else None


def _max_selection_metric(context: _CandidateContext, key: str) -> float | None:
    values = [_metric(result, key) for result in context.selection_results]
    clean = [value for value in values if value is not None]
    return max(clean) if clean else None


def _min_walk_forward_value(context: _CandidateContext, key: str) -> float | None:
    values = [_as_optional_float(summary.get(key)) for summary in context.walk_forward_summaries]
    clean = [value for value in values if value is not None]
    return min(clean) if clean else None


def _max_walk_forward_value(context: _CandidateContext, key: str) -> float | None:
    values = [_as_optional_float(summary.get(key)) for summary in context.walk_forward_summaries]
    clean = [value for value in values if value is not None]
    return max(clean) if clean else None


def _min_capital_goal_metric(context: _CandidateContext, key: str) -> float | None:
    values = []
    for result in context.selection_results:
        review = result.get("capital_goal_fit_review", {})
        if isinstance(review, dict):
            values.append(_as_optional_float(review.get(key)))
    clean = [value for value in values if value is not None]
    return min(clean) if clean else None


def _max_trend_filter_days(context: _CandidateContext) -> int:
    values = []
    for result in context.selection_results:
        values.append(int(_as_float(result.get("trend_filter_active_days"))))
    for summary in context.walk_forward_summaries:
        values.append(int(_as_float(summary.get("trend_filter_active_days"))))
    return max(values) if values else 0


def _is_trend_candidate(context: _CandidateContext) -> bool:
    if "trend_filtered" in context.name:
        return True
    return any(bool(result.get("trend_filter")) for result in context.selection_results)


def _metric(result: dict[str, Any], key: str) -> float | None:
    if key in result:
        return _as_optional_float(result.get(key))
    metrics = result.get("metrics", {})
    if isinstance(metrics, dict) and key in metrics:
        return _as_optional_float(metrics.get(key))
    return None


def _format_metric(key: str, value: float) -> str:
    if key == "sharpe_ratio":
        return f"{value:.2f}"
    return f"{value:.2%}"


def _as_optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float:
    return _as_optional_float(value) or 0.0


def _first_items(items: list[str], *, limit: int) -> list[str]:
    return _unique([item for item in items if item])[:limit]


def _unique(items: Iterable[str]) -> list[str]:
    seen = set()
    unique = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "priority",
        "candidate",
        "category",
        "trigger",
        "recommendation",
        "rationale",
        "evidence",
        "command_hint",
        "allowed_stage",
        "status",
        "can_enter_paper",
        "can_enter_micro_live_ready",
        "can_generate_broker_orders",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
