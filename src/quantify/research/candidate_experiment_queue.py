"""Pre-registered experiment queue for strategy candidates.

The queue converts candidate hypotheses into falsifiable research tasks. It is
only a work order for offline validation; it never grants live-trading approval.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from quantify.research.candidate_hypotheses import (
    CandidateHypothesis,
    CandidateHypothesisCatalog,
    build_candidate_hypothesis_catalog,
)


QUEUE_STATUS = "WAITING_FOR_REAL_DATA"
COMMON_REQUIRED_INPUTS = [
    "Passing source QA review with filled data_source_qa_answers.json.",
    "Passing offline intake with non-template recent A-share daily bars.",
    "A run manifest tying config, cache, sample windows, and data fingerprints together.",
    "Data audit, real data gate, and data coverage reports with no unresolved BLOCK.",
]
COMMON_SUCCESS_CRITERIA = [
    "Out-of-sample evidence is present and not materially worse than in-sample evidence.",
    "Walk-forward validation has enough windows and no unresolved BLOCK.",
    "Cost stress, slippage stress, and parameter perturbation do not create a BLOCK.",
    "Reject rate, turnover, max drawdown, and liquidity flags stay inside configured budgets.",
    "LLM advisory review raises no deterministic override and cannot improve the gate decision.",
]
COMMON_CAPITAL_GOAL_FIT_TESTS = [
    "Run candidate_selection with starting_capital=100000, target_capital=1000000, years=8, and retain the full capital_goal_fit_review.",
    "Record required annual return, return margin, worst walk-forward return, worst drawdown, Sharpe, reject rate, and turnover for every candidate.",
    "Do not select a candidate whose capital_goal_fit_review is BLOCK; top research rank alone is insufficient.",
]
COMMON_RISK_BUDGET_CHECKS = [
    "Max drawdown, turnover, reject rate, liquidity amount, concentration, and cash drag stay inside configured budgets.",
    "Cost stress uses higher slippage, commission, and stamp-tax assumptions before any paper-stage promotion.",
    "Every rebalance records target weight concentration, skipped orders, rejected orders, and target drift.",
]
COMMON_PAPER_ENTRY_REQUIREMENTS = [
    "Data, source QA, offline intake, robustness, walk-forward, factor diagnostics, regime validation, and LLM advisory review have no unresolved BLOCK.",
    "Paper plan produces traceable target holdings, simulated orders, fills, rejects, cash, positions, NAV, and daily review files.",
    "Paper output remains a manual review artifact; it must not connect to a real broker or submit live orders.",
]
COMMON_ANTI_OVERFIT_CONTROLS = [
    "Candidate priority is pre-registered before seeing real-data results and must not be reordered by attractive backtests.",
    "Hold out out-of-sample windows, walk-forward windows, parameter perturbation, and cost stress before comparing candidates.",
    "Run factor ablation and regime validation to detect one-factor, one-window, or one-market-state accidents.",
    "LLM output may add questions or experiments, but it cannot upgrade deterministic gates or queue priority.",
]
COMMON_STOP_CONDITIONS = [
    "Any deterministic gate returns BLOCK.",
    "Data is demo-only, stale, template-based, or missing source QA evidence.",
    "A candidate relies on one factor component after diagnostics.",
    "A candidate cannot produce paper-stage orders with traceable rejects and fills.",
    "Human approval is missing for a stage that requires approval.",
]
COMMON_PROHIBITED_ACTIONS = [
    "Do not treat queue priority as expected return.",
    "Do not skip earlier evidence gates because a later backtest looks attractive.",
    "Do not connect experiments to real broker order submission.",
    "Do not let LLM output change queue priority or deterministic decisions.",
]
COMMON_ARTIFACTS = [
    "candidate_experiment_evidence.json",
    "candidate_walk_forward_report.json",
    "candidate_factor_diagnostics.json",
    "candidate_regime_validation_report.json",
    "candidate_stress_matrix.json",
    "candidate_selection.json",
    "llm_review.json",
]
OHLCV_ONLY_REQUIRED_INPUTS = [
    "Audited OHLCV bars, calendar, stock_info, and source QA evidence; point-in-time fundamentals are not required for this candidate.",
    "Explicit note that OHLCV-only evidence cannot validate valuation or accounting quality claims.",
]


@dataclass(frozen=True, slots=True)
class CandidateExperiment:
    priority: int
    candidate: str
    data_dependency: str
    intended_regimes: list[str]
    objective: str
    rationale: str
    required_inputs: list[str]
    command_sequence: list[str]
    success_criteria: list[str]
    falsification_tests: list[str]
    stop_conditions: list[str]
    artifacts: list[str]
    prohibited_actions: list[str]
    capital_goal_fit_tests: list[str] = field(default_factory=list)
    minimum_evidence_window: dict[str, Any] = field(default_factory=dict)
    risk_budget_checks: list[str] = field(default_factory=list)
    paper_entry_requirements: list[str] = field(default_factory=list)
    anti_overfit_controls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority": self.priority,
            "candidate": self.candidate,
            "data_dependency": self.data_dependency,
            "intended_regimes": self.intended_regimes,
            "objective": self.objective,
            "rationale": self.rationale,
            "required_inputs": self.required_inputs,
            "command_sequence": self.command_sequence,
            "success_criteria": self.success_criteria,
            "falsification_tests": self.falsification_tests,
            "stop_conditions": self.stop_conditions,
            "artifacts": self.artifacts,
            "prohibited_actions": self.prohibited_actions,
            "capital_goal_fit_tests": self.capital_goal_fit_tests,
            "minimum_evidence_window": self.minimum_evidence_window,
            "risk_budget_checks": self.risk_budget_checks,
            "paper_entry_requirements": self.paper_entry_requirements,
            "anti_overfit_controls": self.anti_overfit_controls,
        }


@dataclass(frozen=True, slots=True)
class CandidateExperimentQueue:
    status: str
    as_of: str | None
    experiment_count: int
    experiments: list[CandidateExperiment]
    required_evidence_before_running: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "as_of": self.as_of,
            "experiment_count": self.experiment_count,
            "experiments": [experiment.to_dict() for experiment in self.experiments],
            "required_evidence_before_running": self.required_evidence_before_running,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Candidate Experiment Queue: {self.status}",
            "",
            f"- As of: `{self.as_of or 'unspecified'}`",
            f"- Experiment count: {self.experiment_count}",
            "",
            "This queue is a pre-registered research plan, not a strategy ranking or live trading instruction.",
            "",
            "## Required Evidence Before Running",
        ]
        lines.extend(f"- {item}" for item in self.required_evidence_before_running)
        lines.extend(["", "## Experiments"])
        for experiment in self.experiments:
            lines.extend(
                [
                    "",
                    f"### {experiment.priority}. `{experiment.candidate}`",
                    "",
                    f"- Data dependency: `{experiment.data_dependency}`",
                    "- Intended regimes: " + "; ".join(experiment.intended_regimes or ["unknown"]),
                    f"- Objective: {experiment.objective}",
                    f"- Rationale: {experiment.rationale}",
                    "",
                    "Command sequence:",
                ]
            )
            lines.extend(f"- `{command}`" for command in experiment.command_sequence)
            lines.append("")
            lines.append("Minimum evidence window:")
            lines.extend(
                f"- `{key}`: {value}"
                for key, value in experiment.minimum_evidence_window.items()
            )
            lines.append("")
            lines.append("Capital goal fit tests:")
            lines.extend(f"- {item}" for item in experiment.capital_goal_fit_tests)
            lines.append("")
            lines.append("Risk budget checks:")
            lines.extend(f"- {item}" for item in experiment.risk_budget_checks)
            lines.append("")
            lines.append("Paper entry requirements:")
            lines.extend(f"- {item}" for item in experiment.paper_entry_requirements)
            lines.append("")
            lines.append("Anti-overfit controls:")
            lines.extend(f"- {item}" for item in experiment.anti_overfit_controls)
            lines.append("")
            lines.append("Success criteria:")
            lines.extend(f"- {item}" for item in experiment.success_criteria)
            lines.append("")
            lines.append("Falsification tests:")
            lines.extend(f"- {item}" for item in experiment.falsification_tests)
            lines.append("")
            lines.append("Stop conditions:")
            lines.extend(f"- {item}" for item in experiment.stop_conditions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_candidate_experiment_queue(
    cfg,
    *,
    as_of: str | None = None,
    catalog: CandidateHypothesisCatalog | None = None,
) -> CandidateExperimentQueue:
    hypothesis_catalog = catalog or build_candidate_hypothesis_catalog(cfg, as_of=as_of)
    experiments = [
        _build_experiment(candidate)
        for candidate in sorted(hypothesis_catalog.candidates, key=lambda item: _priority(item.name))
    ]
    return CandidateExperimentQueue(
        status=QUEUE_STATUS,
        as_of=as_of,
        experiment_count=len(experiments),
        experiments=experiments,
        required_evidence_before_running=COMMON_REQUIRED_INPUTS,
        prohibited_actions=COMMON_PROHIBITED_ACTIONS,
    )


def write_candidate_experiment_queue(
    queue: CandidateExperimentQueue,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "candidate_experiment_queue.json").write_text(
        json.dumps(queue.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "candidate_experiment_queue.md").write_text(queue.to_markdown(), encoding="utf-8")
    return root


def _build_experiment(candidate: CandidateHypothesis) -> CandidateExperiment:
    profile = _profile(candidate.name)
    required_inputs = COMMON_REQUIRED_INPUTS + list(profile["extra_inputs"])
    if _is_ohlcv_only(candidate):
        required_inputs.extend(OHLCV_ONLY_REQUIRED_INPUTS)
    return CandidateExperiment(
        priority=_priority(candidate.name),
        candidate=candidate.name,
        data_dependency=candidate.data_dependency,
        intended_regimes=candidate.intended_regimes,
        objective=str(profile["objective"]),
        rationale=str(profile["rationale"]),
        required_inputs=required_inputs,
        command_sequence=_commands(candidate.name),
        success_criteria=COMMON_SUCCESS_CRITERIA + list(profile["success_criteria"]),
        falsification_tests=list(profile["falsification_tests"]),
        stop_conditions=COMMON_STOP_CONDITIONS + list(profile["stop_conditions"]),
        artifacts=COMMON_ARTIFACTS,
        prohibited_actions=COMMON_PROHIBITED_ACTIONS,
        capital_goal_fit_tests=COMMON_CAPITAL_GOAL_FIT_TESTS + list(profile["capital_goal_fit_tests"]),
        minimum_evidence_window=_minimum_evidence_window(candidate),
        risk_budget_checks=_risk_budget_checks(candidate) + list(profile["risk_budget_checks"]),
        paper_entry_requirements=COMMON_PAPER_ENTRY_REQUIREMENTS + list(profile["paper_entry_requirements"]),
        anti_overfit_controls=COMMON_ANTI_OVERFIT_CONTROLS + list(profile["anti_overfit_controls"]),
    )


def _priority(name: str) -> int:
    order = {
        "price_volume_defensive": 1,
        "low_turnover_price_volume": 2,
        "low_turnover_low_concentration_price_volume": 3,
        "trend_filtered_price_volume": 4,
        "trend_filtered_quarterly_price_volume": 5,
        "trend_filtered_quarterly_low_concentration_price_volume": 6,
        "defensive_scaled_quarterly_price_volume": 7,
        "stable_universe_slow_signal_price_volume": 8,
        "long_momentum_liquidity_monthly_price_volume": 9,
        "liquidity_neutral_momentum_guard_price_volume": 10,
        "defensive_cash_guard_price_volume": 11,
        "risk_off_cash_stop_price_volume": 12,
        "regime_pause_price_volume": 13,
        "core_multifactor": 14,
        "defensive_low_vol": 15,
        "trend_filtered_core": 16,
        "value_low_vol": 17,
        "momentum_quality": 18,
    }
    return order.get(name, 99)


def _commands(candidate: str) -> list[str]:
    return [
        "python examples/run_candidate_experiment_evidence.py --source-report-dir results/research --output-dir results/research/<timestamp>",
        "python examples/run_candidate_walk_forward.py --config config/research_recent.yaml --output-dir results/research/<timestamp>",
        f"python examples/run_candidate_factor_diagnostics.py --config config/research_recent.yaml --output-dir results/research/<timestamp> --candidate {candidate}",
        "python examples/run_candidate_regime_validation.py --config config/research_recent.yaml --output-dir results/research/<timestamp>",
        f"python examples/run_candidate_stress_matrix.py --config config/research_recent.yaml --output-dir results/research/<timestamp> --candidate {candidate}",
        "python examples/run_candidate_selection.py --config config/research_recent.yaml --output-dir results/research/<timestamp> --starting-capital 100000 --target-capital 1000000 --years 8",
        "python examples/run_llm_review.py --report-dir results/research/<timestamp> --stage paper",
    ]


def _profile(name: str) -> dict[str, list[str] | str]:
    profiles: dict[str, dict[str, list[str] | str]] = {
        "price_volume_defensive": {
            "objective": "Validate the first OHLCV-only candidate before any PIT-fundamental strategy comparison.",
            "rationale": (
                "TongDaXin or vendor daily-bar exports can support price-volume research earlier than audited "
                "fundamental research, but only after source QA and offline intake pass."
            ),
            "extra_inputs": [
                "Verified adjusted OHLCV bars with amount, calendar coverage, and stock_info hygiene fields."
            ],
            "success_criteria": [
                "The candidate remains stable across walk-forward, cost stress, and factor diagnostics without using fundamentals."
            ],
            "capital_goal_fit_tests": [
                "Confirm the OHLCV-only path can plausibly reach the required compounding path without valuation or accounting-quality claims."
            ],
            "risk_budget_checks": [
                "Liquidity and low-volatility filters must reduce execution risk without becoming the only source of evidence."
            ],
            "paper_entry_requirements": [
                "Paper reviews explicitly label this as OHLCV-only and forbid valuation, profitability, or balance-sheet conclusions."
            ],
            "anti_overfit_controls": [
                "Rerun the same OHLCV-only recipe after PIT fundamentals are available; material holding or risk-profile drift triggers WATCH."
            ],
            "falsification_tests": [
                "Remove liquidity and low-volatility components one at a time to detect single-theme dependency.",
                "Rerun after adding vetted PIT fundamentals and check whether holdings or risk profile shift materially.",
            ],
            "stop_conditions": [
                "Stop if OHLCV adjustment, source license, or export timestamp evidence is unresolved.",
                "Stop if factor diagnostics show the candidate is only a liquidity screen in disguise.",
            ],
        },
        "low_turnover_price_volume": {
            "objective": "Test whether an OHLCV-only low-turnover defensive variant improves cost and drawdown resilience.",
            "rationale": (
                "The monthly price-volume candidate can have high turnover; a quarterly, broader basket may be "
                "more suitable for small-account compounding if it preserves enough return."
            ),
            "extra_inputs": [
                "Verified adjusted OHLCV bars with enough history to compare monthly and quarterly turnover."
            ],
            "success_criteria": [
                "Turnover and cost sensitivity improve versus price_volume_defensive without worsening worst-window drawdown."
            ],
            "capital_goal_fit_tests": [
                "Check whether lower turnover creates a better drawdown-adjusted compounding path, not merely lower activity."
            ],
            "risk_budget_checks": [
                "Quarterly holding periods must not increase stale-position drawdown or liquidity exit risk."
            ],
            "paper_entry_requirements": [
                "Paper review records holding age, target drift, turnover, and any delayed exits at every rebalance."
            ],
            "anti_overfit_controls": [
                "Compare against the monthly OHLCV baseline on identical windows and cost assumptions."
            ],
            "falsification_tests": [
                "Run monthly versus quarterly cadence on the same factors and windows.",
                "Stress delayed-exit windows where low turnover could increase drawdown.",
            ],
            "stop_conditions": [
                "Stop if reduced turnover does not survive high-cost stress or worsens adverse-window drawdown.",
            ],
        },
        "low_turnover_low_concentration_price_volume": {
            "objective": "Test whether lower concentration improves the quarterly low-turnover OHLCV-only variant.",
            "rationale": (
                "Real-cache stress suggested that lower concentration slightly improved drawdown and Sharpe, so this "
                "experiment checks whether the effect survives full comparison and walk-forward evidence."
            ),
            "extra_inputs": [
                "Real-cache evidence from the low_turnover_price_volume stress matrix and walk-forward comparison."
            ],
            "success_criteria": [
                "Lower concentration improves drawdown or Sharpe versus low_turnover_price_volume without collapsing return margin.",
                "High-cost and wider-basket stress remain comparable or better than the baseline low-turnover variant.",
            ],
            "capital_goal_fit_tests": [
                "Check whether lower concentration raises the return-to-drawdown tradeoff enough to matter for the compounding path."
            ],
            "risk_budget_checks": [
                "Compare concentration, turnover, reject rate, and worst walk-forward drawdown against low_turnover_price_volume."
            ],
            "paper_entry_requirements": [
                "Paper review records concentration, holding age, target drift, and any execution relief from the lower-weight cap."
            ],
            "anti_overfit_controls": [
                "Compare against the same candidate with the original max_weight and against the current low-turnover baseline."
            ],
            "falsification_tests": [
                "Run the same quarterly factor recipe at the original and lowered max_weight on identical windows.",
                "Check whether any gain disappears under high-cost stress or walk-forward tails.",
            ],
            "stop_conditions": [
                "Stop if lower concentration only lowers return without materially improving drawdown or execution cost.",
            ],
        },
        "trend_filtered_price_volume": {
            "objective": "Test whether a broad-trend exposure filter reduces OHLCV-only candidate damage in weak markets.",
            "rationale": (
                "The current recent A-share context is defensive/WATCH; an OHLCV-only trend-filtered variant "
                "can test whether reduced exposure improves drawdown without pretending to approve paper trading."
            ),
            "extra_inputs": [
                "Audited OHLCV bars with enough history to compute a broad universe trend proxy."
            ],
            "success_criteria": [
                "Adverse-window drawdown improves versus price_volume_defensive without turning the strategy into mostly cash.",
                "Cash drag and missed-rebound cost remain visible in candidate selection and paper planning artifacts.",
            ],
            "capital_goal_fit_tests": [
                "Quantify whether trend-filter cash drag keeps annualized return below the required compounding path."
            ],
            "risk_budget_checks": [
                "Filter-active days, target exposure scale, turnover, drawdown, and cash drag must be recorded together."
            ],
            "paper_entry_requirements": [
                "Paper review records every filter activation, exposure cut, and missed-rebound review note."
            ],
            "anti_overfit_controls": [
                "Compare filtered and unfiltered price-volume candidates on identical windows and forbid tuning the filter from only the worst window."
            ],
            "falsification_tests": [
                "Compare filtered versus unfiltered price_volume_defensive on identical walk-forward windows.",
                "Measure missed-rebound cost after filter activation and require it in the next LLM advisory review.",
            ],
            "stop_conditions": [
                "Stop if the filter reduces drawdown only by creating excessive cash drag.",
                "Stop if active filter days do not line up with independently reviewed weak-market context.",
            ],
        },
        "trend_filtered_quarterly_price_volume": {
            "objective": "Test whether quarterly rebalance improves the trend-filtered OHLCV-only candidate.",
            "rationale": (
                "Stress matrix evidence showed the quarterly cadence for trend filtering was materially better than "
                "the monthly default, so this experiment checks whether the improvement holds in the full queue."
            ),
            "extra_inputs": [
                "Real-cache evidence from the trend_filtered_price_volume stress matrix and walk-forward comparison."
            ],
            "success_criteria": [
                "Quarterly rebalance improves annualized return and Sharpe versus trend_filtered_price_volume without breaching drawdown limits.",
                "Cash drag and missed-rebound cost remain visible and do not dominate the result.",
            ],
            "capital_goal_fit_tests": [
                "Quantify whether the quarterly cadence closes enough of the return gap toward the capital goal path."
            ],
            "risk_budget_checks": [
                "Compare turnover, reject rate, drawdown, and active filter days against the monthly trend-filtered baseline."
            ],
            "paper_entry_requirements": [
                "Paper review records filter-active days, quarterly target drift, and missed-rebound notes."
            ],
            "anti_overfit_controls": [
                "Compare quarterly and monthly trend-filtered runs on identical windows and stress assumptions."
            ],
            "falsification_tests": [
                "Run the same trend-filtered recipe with monthly and quarterly cadence on identical windows.",
                "Check whether the quarterly result survives cost inflation and walk-forward tails.",
            ],
            "stop_conditions": [
                "Stop if quarterly cadence only improves one sample path and not walk-forward resilience.",
            ],
        },
        "trend_filtered_quarterly_low_concentration_price_volume": {
            "objective": "Test whether the lower-concentration quarterly trend-filtered stress path can become a robust candidate.",
            "rationale": (
                "Recent stress evidence showed the lower max-weight quarterly trend-filtered path had better drawdown, "
                "turnover, and Sharpe characteristics than the baseline stress path, so this candidate retests it as a "
                "pre-registered OHLCV-only research variant."
            ),
            "extra_inputs": [
                "Real-cache stress evidence from trend_filtered_quarterly_price_volume lower_concentration scenario."
            ],
            "success_criteria": [
                "Lower concentration improves drawdown or turnover versus trend_filtered_quarterly_price_volume without worsening return margin.",
                "High-cost, walk-forward, and trend-filter-off stress do not erase the lower-concentration advantage.",
            ],
            "capital_goal_fit_tests": [
                "Check whether the lower concentration variant improves risk-adjusted compounding feasibility instead of merely lowering exposure."
            ],
            "risk_budget_checks": [
                "Compare concentration, target drift, turnover, reject rate, drawdown, and filter-active days against the quarterly baseline."
            ],
            "paper_entry_requirements": [
                "Paper review records lower-weight target drift, filter-active days, cash drag, and missed-rebound notes."
            ],
            "anti_overfit_controls": [
                "Compare the lower max_weight and original max_weight variants on identical windows and cost assumptions."
            ],
            "falsification_tests": [
                "Run the quarterly trend-filtered recipe at original and lower max_weight on identical windows.",
                "Check whether lower concentration fails when high-cost or walk-forward tail windows are emphasized.",
            ],
            "stop_conditions": [
                "Stop if lower concentration only lowers return without materially improving drawdown, turnover, or Sharpe.",
            ],
        },
        "defensive_scaled_quarterly_price_volume": {
            "objective": "Test whether defensive-regime exposure scaling improves the quarterly price-volume path.",
            "rationale": (
                "Recent walk-forward evidence split cleanly by regime: neutral windows were profitable while defensive "
                "windows drove losses. This candidate keeps quarterly price-volume participation but cuts exposure "
                "more aggressively when the reviewed market regime is defensive or worse."
            ),
            "extra_inputs": [
                "Candidate regime validation showing defensive bucket losses for trend_filtered_quarterly_price_volume and its low-concentration variant."
            ],
            "success_criteria": [
                "Defensive bucket average return and worst drawdown improve versus both quarterly trend-filtered baselines.",
                "Neutral bucket return remains closer to trend_filtered_quarterly_price_volume than to a mostly-cash guard.",
                "Positive walk-forward ratio improves beyond the current 2/6 evidence without breaching drawdown budget.",
            ],
            "capital_goal_fit_tests": [
                "Check whether defensive scaling improves return margin through fewer adverse losses rather than only lower exposure."
            ],
            "risk_budget_checks": [
                "Compare defensive-gate activations, exposure scale, drawdown, turnover, reject rate, and missed-rebound cost."
            ],
            "paper_entry_requirements": [
                "Paper review records every defensive gate activation, target exposure scale, cash drag, and missed rebound."
            ],
            "anti_overfit_controls": [
                "Compare against trend_filtered_quarterly_price_volume and trend_filtered_quarterly_low_concentration_price_volume on identical windows.",
                "Rerun with defensive gate disabled and with lower concentration to isolate gate effect from concentration effect.",
            ],
            "falsification_tests": [
                "Run identical windows with weak_trend and defensive_or_worse gates.",
                "Check whether defensive scaling fails in neutral rebound windows or merely shifts losses into missed rebounds.",
            ],
            "stop_conditions": [
                "Stop if defensive bucket return remains non-positive and positive-window ratio stays at or below 2/6.",
                "Stop if annualized return falls below the low-concentration variant while drawdown does not improve.",
            ],
        },
        "stable_universe_slow_signal_price_volume": {
            "objective": "Test whether a stable wide universe and slow OHLCV signals reduce structural turnover.",
            "rationale": (
                "Hold-rank buffers, drift thresholds, new-position caps, and score smoothing did not materially "
                "reduce maintenance turnover for the current best research candidate. This experiment changes the "
                "raw signal recipe instead: wider holdings, lower max weight, very low volatility, liquidity, and "
                "long momentum that skips recent short-term moves."
            ),
            "extra_inputs": [
                "Real-cache stress evidence showing turnover-control and score-smoothing ablations failed to reduce maintenance turnover."
            ],
            "success_criteria": [
                "Maintenance turnover improves versus defensive_scaled_quarterly_price_volume without adding order-path controls.",
                "High-cost and wider-basket stress do not erase the slow-signal candidate's return and drawdown profile.",
                "Factor diagnostics show long momentum contributes evidence beyond low volatility and liquidity.",
            ],
            "capital_goal_fit_tests": [
                "Check whether lower structural turnover improves after-cost return margin enough to matter for the compounding path."
            ],
            "risk_budget_checks": [
                "Compare holding age, maintenance turnover, drawdown, reject rate, and stale-position risk against the defensive-scaled baseline."
            ],
            "paper_entry_requirements": [
                "Paper review records slow-signal stale-position risk, maintenance turnover, holding age, and target drift."
            ],
            "anti_overfit_controls": [
                "Compare directly against defensive_scaled_quarterly_price_volume on identical windows before changing any execution controls.",
                "Ablate long momentum, liquidity, and low-volatility components to detect a one-component proxy.",
            ],
            "falsification_tests": [
                "Remove long momentum and verify the candidate is not just a low-volatility/liquidity screen.",
                "Run the same slow-signal recipe with quarterly and monthly cadence to test whether lower turnover is structural.",
                "Reject if maintenance turnover remains high while return margin or Sharpe deteriorates.",
            ],
            "stop_conditions": [
                "Stop if slow signals do not reduce maintenance turnover versus the defensive-scaled baseline.",
                "Stop if slower exits increase adverse-window drawdown or stale-position losses.",
            ],
        },
        "long_momentum_liquidity_monthly_price_volume": {
            "objective": "Test whether the slow-signal basket's useful evidence comes from long momentum plus liquidity.",
            "rationale": (
                "Full diagnostics for stable_universe_slow_signal_price_volume showed low-volatility components "
                "were weak while long momentum and liquidity carried most of the positive component evidence. "
                "This candidate is a pre-registered component ablation, not a promotion of the prior result."
            ),
            "extra_inputs": [
                "Factor diagnostics from stable_universe_slow_signal_price_volume showing low-volatility dilution and long-momentum/liquidity dominance."
            ],
            "success_criteria": [
                "Composite return improves versus stable_universe_slow_signal_price_volume without worse adverse-window drawdown.",
                "Maintenance turnover remains below the defensive-scaled baseline after costs and rejects.",
                "Factor diagnostics do not show the composite is only a single long-momentum or liquidity component.",
            ],
            "capital_goal_fit_tests": [
                "Check whether the component ablation closes the capital-goal return margin without exceeding the drawdown budget."
            ],
            "risk_budget_checks": [
                "Compare momentum concentration, liquidity concentration, maintenance turnover, drawdown, and reject rate against stable_universe_slow_signal_price_volume."
            ],
            "paper_entry_requirements": [
                "Paper review records long-momentum/liquidity concentration, reversals, holding age, turnover, and skipped trades."
            ],
            "anti_overfit_controls": [
                "Compare against stable_universe_slow_signal_price_volume on identical windows before tuning holdings or max_weight.",
                "Run a quarterly-cadence stress to verify the monthly result is not a one-window rebound artifact.",
            ],
            "falsification_tests": [
                "Remove long momentum and liquidity one at a time and reject the candidate if one component explains the composite.",
                "Run monthly versus quarterly cadence on identical windows.",
                "Reject if improved return comes from worse defensive or adverse-window behavior.",
            ],
            "stop_conditions": [
                "Stop if factor diagnostics show a single-component dependency.",
                "Stop if monthly cadence raises turnover above the small-capital budget.",
                "Stop if the candidate only works in one recent rebound window.",
            ],
        },
        "liquidity_neutral_momentum_guard_price_volume": {
            "objective": "Test whether long momentum survives liquidity-neutral residualization and defensive exposure guarding.",
            "rationale": (
                "Full diagnostics for long_momentum_liquidity_monthly_price_volume showed a 0.98 liquidity dependency ratio "
                "and weak defensive buckets. This candidate removes the direct liquidity component, uses a liquidity-neutral "
                "long-momentum residual, and adds a defensive-or-worse exposure cut before any execution-control overlay."
            ),
            "extra_inputs": [
                "Full diagnostics from long_momentum_liquidity_monthly_price_volume showing liquidity dependency and defensive-regime weakness."
            ],
            "success_criteria": [
                "Defensive bucket return and drawdown improve versus long_momentum_liquidity_monthly_price_volume.",
                "Capital-goal return margin does not deteriorate materially after liquidity neutralization and defensive guarding.",
                "Factor diagnostics show liquidity-neutral momentum contributes beyond very low volatility.",
            ],
            "capital_goal_fit_tests": [
                "Check whether liquidity neutralization plus defensive guarding improves drawdown-adjusted compounding feasibility, not just cash drag."
            ],
            "risk_budget_checks": [
                "Compare liquidity-neutral residual exposure, defensive-gate activations, cash drag, turnover, drawdown, and reject rate."
            ],
            "paper_entry_requirements": [
                "Paper review records liquidity-neutral momentum exposure, defensive gate activations, cash drag, missed rebounds, and skipped trades."
            ],
            "anti_overfit_controls": [
                "Compare against long_momentum_liquidity_monthly_price_volume and trend-filter-off on identical windows before tuning thresholds.",
                "Run quarterly and monthly cadence stress to separate signal robustness from rebalance timing.",
            ],
            "falsification_tests": [
                "Compare liquidity-neutral momentum with the original long momentum plus liquidity composite on identical windows.",
                "Run trend-filter-off and stronger-filter stress to isolate defensive guard benefit from cash drag.",
                "Reject if neutralization removes return while the defensive bucket remains weak.",
            ],
            "stop_conditions": [
                "Stop if liquidity-neutral return disappears versus the unguarded ablation.",
                "Stop if defensive bucket losses remain non-positive without a drawdown improvement.",
                "Stop if factor diagnostics show the candidate is only a very-low-volatility proxy.",
            ],
        },
        "defensive_cash_guard_price_volume": {
            "objective": "Test whether stronger OHLCV-only cash guarding can reduce defensive-regime losses.",
            "rationale": (
                "Recent A-share evidence showed ordinary low-turnover and trend-filtered price-volume "
                "candidates still lost money in defensive windows; this variant tests lower concentration "
                "and stronger weak-market exposure cuts without claiming paper readiness."
            ),
            "extra_inputs": [
                "Audited OHLCV bars with enough history to compute broad trend weakness and compare cash drag."
            ],
            "success_criteria": [
                "Defensive-regime total return and drawdown improve versus low_turnover_price_volume and trend_filtered_price_volume.",
                "Improvement is not explained only by being mostly uninvested.",
            ],
            "capital_goal_fit_tests": [
                "Quantify whether stronger cash guard protects capital without making the one-million path mathematically impossible."
            ],
            "risk_budget_checks": [
                "Record target exposure, cash drag, turnover, drawdown, and missed-rebound cost together."
            ],
            "paper_entry_requirements": [
                "Paper review records every filter activation, target exposure reduction, and cash-drag note."
            ],
            "anti_overfit_controls": [
                "Compare against the two failed OHLCV defensive candidates on identical windows before changing thresholds."
            ],
            "falsification_tests": [
                "Compare baseline, high-cost, lower-concentration, trend-filter-off, and stronger-filter scenarios.",
                "Run regime validation and reject if defensive buckets remain non-positive.",
            ],
            "stop_conditions": [
                "Stop if defensive-regime losses remain non-positive after stronger cash guard.",
                "Stop if lower drawdown comes only from excessive cash drag or missed rebound.",
            ],
        },
        "risk_off_cash_stop_price_volume": {
            "objective": "Test whether a strict OHLCV-only cash stop can avoid recent defensive-window losses.",
            "rationale": (
                "Partial exposure cuts still lost money in the recent defensive A-share window; a full weak-trend "
                "cash stop tests whether the right next step is risk avoidance rather than another invested basket."
            ),
            "extra_inputs": [
                "Audited OHLCV bars with enough history to compute broad trend weakness, exits, re-entries, and missed rebounds."
            ],
            "success_criteria": [
                "Defensive-regime return improves versus the partial cash-guard candidate without creating a non-investable cash-only profile.",
                "Neutral and rebound windows retain enough return margin for the one-million compounding path.",
            ],
            "capital_goal_fit_tests": [
                "Quantify whether full-cash stops protect drawdown while preserving a positive return margin after costs."
            ],
            "risk_budget_checks": [
                "Record cash-stop activations, target exposure, re-entry timing, turnover, and missed-rebound cost together."
            ],
            "paper_entry_requirements": [
                "Paper review records every full-cash activation and re-entry; no broker order instructions are generated."
            ],
            "anti_overfit_controls": [
                "Compare strict cash stop against partial cash guard and trend-filter-off on identical windows before tuning thresholds."
            ],
            "falsification_tests": [
                "Compare baseline, high-cost, wider-basket, trend-filter-off, and stronger-filter scenarios.",
                "Reject if lower drawdown comes mostly from avoiding all exposure while annualized return remains below the capital-goal path.",
            ],
            "stop_conditions": [
                "Stop if full cash stops do not improve the defensive failed window.",
                "Stop if missed-rebound cost or turnover makes the compounding path unrealistic.",
            ],
        },
        "regime_pause_price_volume": {
            "objective": "Test whether explicit regime-pause behavior is better than a generic broad-trend tweak.",
            "rationale": (
                "The prior OHLCV-only recipes already covered slower turnover, broader baskets, and broad-trend "
                "exposure cuts; this candidate is reserved for an explicit pause-and-resume regime path that should "
                "stop risk-taking when weak-market evidence says pause, then resume only after a reviewed context change."
            ),
            "extra_inputs": [
                "Audited OHLCV bars plus reviewed market-regime evidence that can justify explicit pause and resume points."
            ],
            "success_criteria": [
                "Pause triggers are explicit and reviewable instead of looking like another broad-trend scaling tweak.",
                "The candidate stays distinct from a generic broad-trend tweak by producing explicit pause and resume episodes.",
                "Pause episodes reduce adverse-window damage without erasing the return path via excessive missed rebounds.",
            ],
            "capital_goal_fit_tests": [
                "Check whether explicit pause/resume behavior still leaves enough return margin after cash drag and missed rebounds."
            ],
            "risk_budget_checks": [
                "Record pause triggers, resume triggers, exposure cuts, and missed-rebound cost as separate evidence items."
            ],
            "paper_entry_requirements": [
                "Paper review must show each pause decision is explicit and human-reviewable before any paper-stage discussion."
            ],
            "anti_overfit_controls": [
                "Compare pause-on versus pause-off runs on the same windows before tuning the pause trigger or resume threshold."
            ],
            "falsification_tests": [
                "Compare the candidate against generic broad-trend scaling and full cash-stop variants on identical windows.",
                "Reject the candidate if its behavior is indistinguishable from a generic trend-filter tweak."
            ],
            "stop_conditions": [
                "Stop if explicit pause behavior does not differ from the existing broad-trend recipes.",
                "Stop if pause/resume timing destroys the compounding path through missed rebounds."
            ],
        },
        "core_multifactor": {
            "objective": "Establish the diversified baseline that every other candidate must beat or complement.",
            "rationale": "It is the most balanced candidate and should become the benchmark for stability.",
            "extra_inputs": ["Full factor component coverage for momentum, low volatility, value, quality, and liquidity."],
            "success_criteria": ["At least two factor components contribute useful evidence across windows."],
            "capital_goal_fit_tests": [
                "Use the core candidate as the benchmark for required return margin and drawdown budget before testing narrower sleeves."
            ],
            "risk_budget_checks": [
                "Industry, market-cap, liquidity, and factor-component concentration must be reviewed before paper promotion."
            ],
            "paper_entry_requirements": [
                "Paper plan records factor score drift and confirms at least two components still contribute at each rebalance review."
            ],
            "anti_overfit_controls": [
                "Run component ablation across the same windows used for the composite before ranking it against other candidates."
            ],
            "falsification_tests": [
                "Remove each factor component one at a time and verify the composite is not a one-factor accident.",
                "Compare performance across neutral, defensive, and adverse windows.",
            ],
            "stop_conditions": ["Stop if factor diagnostics show one component explains most of the evidence."],
        },
        "defensive_low_vol": {
            "objective": "Test whether lower volatility can reduce drawdown enough for compounding discipline.",
            "rationale": "A first-capital system needs survivability before upside chasing.",
            "extra_inputs": ["Enough adverse or defensive windows to evaluate drawdown behavior."],
            "success_criteria": ["Drawdown improves versus core_multifactor after costs without excessive return collapse."],
            "capital_goal_fit_tests": [
                "Check whether lower drawdown improves survivability without making the one-million path mathematically implausible."
            ],
            "risk_budget_checks": [
                "Drawdown reduction must survive higher cost stress and not rely on crowded low-volatility names."
            ],
            "paper_entry_requirements": [
                "Paper review compares realized drawdown, turnover, and opportunity cost against core_multifactor."
            ],
            "anti_overfit_controls": [
                "Evaluate defensive windows and risk-on windows separately so the candidate is not optimized only for weak markets."
            ],
            "falsification_tests": [
                "Stress higher slippage and commission assumptions.",
                "Compare defensive windows against the core candidate.",
            ],
            "stop_conditions": ["Stop if drawdown is not meaningfully better than the core candidate."],
        },
        "trend_filtered_core": {
            "objective": "Test whether broad-trend exposure reduction improves adverse-window survival.",
            "rationale": "A filter can be useful only if it reduces damage without destroying the return path.",
            "extra_inputs": ["Broad market trend proxy coverage for the same sample window."],
            "success_criteria": ["Filtered core improves adverse windows while keeping the capital goal path plausible."],
            "capital_goal_fit_tests": [
                "Quantify cash drag and missed-rebound cost against the required annual return for the capital goal."
            ],
            "risk_budget_checks": [
                "Trend filter exposure cuts must reduce adverse-window damage without hiding uninvested cash drag."
            ],
            "paper_entry_requirements": [
                "Paper state records active filter days, target exposure scale, and reasons for reduced exposure."
            ],
            "anti_overfit_controls": [
                "Compare filtered and unfiltered core on identical windows and forbid tuning the filter from only failed windows."
            ],
            "falsification_tests": [
                "Compare filtered and unfiltered core on identical walk-forward windows.",
                "Measure missed-rebound cost after filter activation.",
            ],
            "stop_conditions": ["Stop if cash drag makes the one-million target path unrealistic."],
        },
        "value_low_vol": {
            "objective": "Test whether value plus low volatility adds a slower mean-reversion sleeve.",
            "rationale": "It may diversify away from pure momentum behavior if valuation data is trustworthy.",
            "extra_inputs": ["Valuation and fundamental field provenance with point-in-time notes."],
            "success_criteria": ["Non-PIT leakage risk is resolved or explicitly downgraded before ranking."],
            "capital_goal_fit_tests": [
                "Confirm slower value evidence still keeps return margin above the capital goal requirement after costs."
            ],
            "risk_budget_checks": [
                "Value exposure must not become stale-fundamental, low-liquidity, or single-industry concentration."
            ],
            "paper_entry_requirements": [
                "Paper review records whether stale or lagged fundamentals drive target holdings."
            ],
            "anti_overfit_controls": [
                "Lag valuation fields and rerun without them to test whether apparent value evidence is lookahead leakage."
            ],
            "falsification_tests": [
                "Rerun with valuation fields removed or lagged.",
                "Check whether stale fundamentals dominate target holdings.",
            ],
            "stop_conditions": ["Stop if valuation provenance is unclear or leakage risk remains unresolved."],
        },
        "momentum_quality": {
            "objective": "Test whether momentum-quality can add upside without violating drawdown and turnover budgets.",
            "rationale": "This candidate is more aggressive and should be tested after the defensive baseline.",
            "extra_inputs": ["Turnover, industry concentration, and cost stress evidence with enough reversal windows."],
            "success_criteria": ["Higher upside survives cost stress and does not breach drawdown or concentration budgets."],
            "capital_goal_fit_tests": [
                "Upside must add return margin after turnover cost without breaching the drawdown budget for compounding discipline."
            ],
            "risk_budget_checks": [
                "Use stricter turnover, theme concentration, and reversal-window checks than the core candidate."
            ],
            "paper_entry_requirements": [
                "Paper loop flags any rebalance dominated by one hot industry, concept, or momentum cluster."
            ],
            "anti_overfit_controls": [
                "Include reversal and defensive windows before promotion so recent winners do not define the whole test."
            ],
            "falsification_tests": [
                "Increase cost assumptions and lower rebalance frequency.",
                "Check whether returns concentrate in one hot industry or theme.",
            ],
            "stop_conditions": ["Stop if turnover, cost sensitivity, or theme concentration exceeds budget."],
        },
    }
    return profiles.get(name, _fallback_profile(name))


def _fallback_profile(name: str) -> dict[str, list[str] | str]:
    return {
        "objective": f"Validate {name} only after a bespoke experiment profile is written.",
        "rationale": "Unknown candidates should not outrank named candidates without a reviewed plan.",
        "extra_inputs": ["Reviewed bespoke hypothesis and validation plan."],
        "success_criteria": ["Bespoke success criteria are written before the candidate is evaluated."],
        "capital_goal_fit_tests": ["Write bespoke capital-goal fit tests before the candidate is evaluated."],
        "risk_budget_checks": ["Write bespoke risk-budget checks before the candidate is evaluated."],
        "paper_entry_requirements": ["Write bespoke paper-entry requirements before paper planning."],
        "anti_overfit_controls": ["Write bespoke anti-overfit controls before the candidate is evaluated."],
        "falsification_tests": ["Write candidate-specific falsification tests before running research."],
        "stop_conditions": ["Stop until a bespoke profile exists."],
    }


def _minimum_evidence_window(candidate: CandidateHypothesis) -> dict[str, Any]:
    return {
        "minimum_total_trading_days": 720,
        "minimum_out_of_sample_trading_days": 240,
        "minimum_walk_forward_windows": 6,
        "minimum_regime_windows": ["neutral", "defensive", "adverse when available"],
        "minimum_paper_observation_weeks_before_micro_live_ready": "4-8",
        "sample_split_required": True,
        "requires_trend_proxy_window": candidate.trend_filter,
        "requires_pit_fundamental_history": not _is_ohlcv_only(candidate),
    }


def _risk_budget_checks(candidate: CandidateHypothesis) -> list[str]:
    return COMMON_RISK_BUDGET_CHECKS + [
        f"Carry configured holdings={candidate.n_holdings}, max_weight={candidate.max_weight:.2%}, and rebalance={candidate.rebalance} into research, selection, and paper artifacts.",
    ]


def _is_ohlcv_only(candidate: CandidateHypothesis) -> bool:
    fundamental_factors = {"value_ep", "quality_roe"}
    return not fundamental_factors.intersection(candidate.factors)
