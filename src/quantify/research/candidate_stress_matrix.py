"""Research-only parameter and cost stress matrix for strategy candidates."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quantify.analytics.metrics import compute_report
from quantify.core.portfolio import Portfolio
from quantify.data.provider import DataProvider
from quantify.engine.paper_broker import PaperBroker, PaperBrokerConfig
from quantify.research.candidates import (
    CandidateSpec,
    TrendFilteredTargetStrategy,
    default_candidate_specs,
    runtime_market_regime,
)
from quantify.research.engine import ResearchEngine
from quantify.research.factors import FactorPipeline
from quantify.research.strategy import MultiFactorStrategyConfig, MultiFactorTargetStrategy
from quantify.research.turnover import summarize_turnover
from quantify.research.universe import UniverseConfig, UniverseFilter

StressStatus = Literal["PASS", "WATCH", "BLOCK"]
REPORT_STATUS = "RESEARCH_ONLY"
PROMOTION_DECISION = "BLOCK"
PROHIBITED_ACTIONS = [
    "Do not treat a stress-matrix PASS as paper approval or micro-live readiness.",
    "Do not connect this output to a broker or generate real order instructions.",
    "Do not use this output as --gate-report-dir for guarded candidate CLIs.",
    "Do not let LLM output upgrade the deterministic promotion decision.",
]
ALLOWED_ACTIONS = [
    "Use stress results to decide the next offline candidate experiment.",
    "Compare turnover, drawdown, reject rate, and cost sensitivity across candidate parameter variants.",
    "Attach this artifact to a human research note as non-promotional evidence.",
]
MISSING_PROMOTION_EVIDENCE = [
    "PASS source QA, guarded offline intake, data audit, and run manifest evidence.",
    "PASS candidate_experiment_readiness.json, candidate_experiment_launch.json, and candidate_experiment_completion.json.",
    "Factor diagnostics, regime validation, walk-forward, cost stress, and parameter perturbation with no unresolved BLOCK.",
    "Paper-stage stability records and human approval before any micro-live readiness claim.",
]


@dataclass(frozen=True, slots=True)
class CandidateStressScenario:
    name: str
    n_holdings: int
    max_weight: float
    rebalance: str
    cost_multiplier: float = 1.0
    trend_filter: bool = False
    trend_scale: float = 0.35
    trend_gate: str = "weak_trend"
    hold_rank_buffer: int = 0
    min_trade_weight: float = 0.0
    max_new_positions: int = 0
    score_smoothing_observations: int = 0
    score_smoothing_step_days: int = 20
    initial_cash: float | None = None
    commission_rate: float | None = None
    min_commission: float | None = None
    stamp_tax: float | None = None
    slippage_bps: float | None = None
    lot_size: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "n_holdings": self.n_holdings,
            "max_weight": self.max_weight,
            "rebalance": self.rebalance,
            "cost_multiplier": self.cost_multiplier,
            "trend_filter": self.trend_filter,
            "trend_scale": self.trend_scale,
            "trend_gate": self.trend_gate,
            "hold_rank_buffer": self.hold_rank_buffer,
            "min_trade_weight": self.min_trade_weight,
            "max_new_positions": self.max_new_positions,
            "score_smoothing_observations": self.score_smoothing_observations,
            "score_smoothing_step_days": self.score_smoothing_step_days,
            "initial_cash": self.initial_cash,
            "commission_rate": self.commission_rate,
            "min_commission": self.min_commission,
            "stamp_tax": self.stamp_tax,
            "slippage_bps": self.slippage_bps,
            "lot_size": self.lot_size,
        }


@dataclass(frozen=True, slots=True)
class CandidateStressResult:
    candidate: str
    scenario: str
    status: StressStatus
    parameters: dict[str, Any]
    metrics: dict[str, float | int]
    order_count: int
    reject_rate: float
    execution_initial_cash: float
    final_cash_ratio: float
    min_commission_hit_count: int
    below_lot_reject_count: int
    avg_turnover_pct: float
    initial_turnover_pct: float
    avg_maintenance_turnover_pct: float
    max_maintenance_turnover_pct: float
    maintenance_turnover_observation_count: int
    trend_filter_active_days: int
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "scenario": self.scenario,
            "status": self.status,
            "parameters": self.parameters,
            "metrics": self.metrics,
            "order_count": self.order_count,
            "reject_rate": self.reject_rate,
            "execution_initial_cash": self.execution_initial_cash,
            "final_cash_ratio": self.final_cash_ratio,
            "min_commission_hit_count": self.min_commission_hit_count,
            "below_lot_reject_count": self.below_lot_reject_count,
            "avg_turnover_pct": self.avg_turnover_pct,
            "initial_turnover_pct": self.initial_turnover_pct,
            "avg_maintenance_turnover_pct": self.avg_maintenance_turnover_pct,
            "max_maintenance_turnover_pct": self.max_maintenance_turnover_pct,
            "maintenance_turnover_observation_count": self.maintenance_turnover_observation_count,
            "trend_filter_active_days": self.trend_filter_active_days,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class CandidateStressSummary:
    candidate: str
    status: StressStatus
    scenario_count: int
    pass_count: int
    watch_count: int
    block_count: int
    baseline_total_return: float
    worst_total_return: float
    worst_max_drawdown: float
    worst_sharpe_ratio: float
    max_reject_rate: float
    max_turnover_pct: float
    max_maintenance_turnover_pct: float
    findings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "status": self.status,
            "scenario_count": self.scenario_count,
            "pass_count": self.pass_count,
            "watch_count": self.watch_count,
            "block_count": self.block_count,
            "baseline_total_return": self.baseline_total_return,
            "worst_total_return": self.worst_total_return,
            "worst_max_drawdown": self.worst_max_drawdown,
            "worst_sharpe_ratio": self.worst_sharpe_ratio,
            "max_reject_rate": self.max_reject_rate,
            "max_turnover_pct": self.max_turnover_pct,
            "max_maintenance_turnover_pct": self.max_maintenance_turnover_pct,
            "findings": self.findings,
        }


@dataclass(frozen=True, slots=True)
class CandidateStressMatrixReport:
    status: str
    promotion_decision: str
    stress_status: StressStatus
    candidate_count: int
    scenario_count: int
    summaries: list[CandidateStressSummary]
    results: list[CandidateStressResult]
    missing_promotion_evidence: list[str]
    allowed_actions: list[str]
    prohibited_actions: list[str]
    can_satisfy_launch_gate: bool = False
    can_enter_paper: bool = False
    can_enter_micro_live_ready: bool = False
    can_generate_broker_orders: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": "candidate_stress_matrix",
            "status": self.status,
            "promotion_decision": self.promotion_decision,
            "stress_status": self.stress_status,
            "candidate_count": self.candidate_count,
            "scenario_count": self.scenario_count,
            "summaries": [summary.to_dict() for summary in self.summaries],
            "results": [result.to_dict() for result in self.results],
            "missing_promotion_evidence": self.missing_promotion_evidence,
            "allowed_actions": self.allowed_actions,
            "prohibited_actions": self.prohibited_actions,
            "can_satisfy_launch_gate": self.can_satisfy_launch_gate,
            "can_enter_paper": self.can_enter_paper,
            "can_enter_micro_live_ready": self.can_enter_micro_live_ready,
            "can_generate_broker_orders": self.can_generate_broker_orders,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Candidate Stress Matrix: {self.status}",
            "",
            f"- Promotion decision: `{self.promotion_decision}`",
            f"- Stress status: `{self.stress_status}`",
            f"- Candidates: {self.candidate_count}",
            f"- Scenario results: {self.scenario_count}",
            "",
            "This is parameter and cost stress evidence for offline research. It cannot approve paper, micro-live readiness, or broker instructions.",
            "",
            "## Candidate Summary",
            "",
            "| candidate | stress | scenarios | pass | watch | block | baseline_return | worst_return | worst_drawdown | worst_sharpe | max_reject | max_turnover | max_maintenance_turnover |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for summary in self.summaries:
            lines.append(
                f"| {summary.candidate} | `{summary.status}` | {summary.scenario_count} | {summary.pass_count} | {summary.watch_count} | {summary.block_count} | {summary.baseline_total_return:.2%} | {summary.worst_total_return:.2%} | {summary.worst_max_drawdown:.2%} | {summary.worst_sharpe_ratio:.2f} | {summary.max_reject_rate:.2%} | {summary.max_turnover_pct:.2%} | {summary.max_maintenance_turnover_pct:.2%} |"
            )
        lines.extend(["", "## Scenario Results", ""])
        lines.append(
            "| candidate | scenario | status | total_return | max_drawdown | sharpe | reject | turnover | maintenance_turnover | trend_days |"
        )
        lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for result in self.results:
            metrics = result.metrics
            lines.append(
                "| {candidate} | `{scenario}` | `{status}` | {ret:.2%} | {dd:.2%} | {sharpe:.2f} | {reject:.2%} | {turnover:.2%} | {maintenance:.2%} | {trend_days} |".format(
                    candidate=result.candidate,
                    scenario=result.scenario,
                    status=result.status,
                    ret=float(metrics.get("total_return", 0.0)),
                    dd=float(metrics.get("max_drawdown", 0.0)),
                    sharpe=float(metrics.get("sharpe_ratio", 0.0)),
                    reject=result.reject_rate,
                    turnover=result.avg_turnover_pct,
                    maintenance=result.avg_maintenance_turnover_pct,
                    trend_days=result.trend_filter_active_days,
                )
            )
        lines.extend(["", "## Findings"])
        for summary in self.summaries:
            lines.append(f"- `{summary.candidate}`")
            lines.extend(f"  - {finding}" for finding in summary.findings)
        lines.extend(["", "## Missing Promotion Evidence"])
        lines.extend(f"- {item}" for item in self.missing_promotion_evidence)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"

    def to_csv_rows(self) -> list[dict[str, Any]]:
        rows = []
        for result in self.results:
            metrics = result.metrics
            rows.append(
                {
                    "candidate": result.candidate,
                    "scenario": result.scenario,
                    "status": result.status,
                    "total_return": metrics.get("total_return", 0.0),
                    "annualized_return": metrics.get("annualized_return", 0.0),
                    "max_drawdown": metrics.get("max_drawdown", 0.0),
                    "sharpe_ratio": metrics.get("sharpe_ratio", 0.0),
                    "reject_rate": result.reject_rate,
                    "execution_initial_cash": result.execution_initial_cash,
                    "final_cash_ratio": result.final_cash_ratio,
                    "min_commission_hit_count": result.min_commission_hit_count,
                    "below_lot_reject_count": result.below_lot_reject_count,
                    "avg_turnover_pct": result.avg_turnover_pct,
                    "initial_turnover_pct": result.initial_turnover_pct,
                    "avg_maintenance_turnover_pct": result.avg_maintenance_turnover_pct,
                    "max_maintenance_turnover_pct": result.max_maintenance_turnover_pct,
                    "maintenance_turnover_observation_count": result.maintenance_turnover_observation_count,
                    "trend_filter_active_days": result.trend_filter_active_days,
                    "n_holdings": result.parameters["n_holdings"],
                    "max_weight": result.parameters["max_weight"],
                    "rebalance": result.parameters["rebalance"],
                    "cost_multiplier": result.parameters["cost_multiplier"],
                    "trend_filter": result.parameters["trend_filter"],
                    "trend_scale": result.parameters["trend_scale"],
                    "trend_gate": result.parameters["trend_gate"],
                    "hold_rank_buffer": result.parameters["hold_rank_buffer"],
                    "min_trade_weight": result.parameters["min_trade_weight"],
                    "max_new_positions": result.parameters["max_new_positions"],
                    "score_smoothing_observations": result.parameters[
                        "score_smoothing_observations"
                    ],
                    "score_smoothing_step_days": result.parameters["score_smoothing_step_days"],
                    "notes": " | ".join(result.notes),
                }
            )
        return rows


def default_candidate_stress_scenarios(spec: CandidateSpec) -> list[CandidateStressScenario]:
    alt_rebalance = "quarterly" if not spec.rebalance.lower().startswith("q") else "monthly"
    wider_holdings = max(spec.n_holdings + 10, int(spec.n_holdings * 1.5))
    scenarios = [
        CandidateStressScenario(
            name="baseline",
            n_holdings=spec.n_holdings,
            max_weight=spec.max_weight,
            rebalance=spec.rebalance,
            trend_filter=spec.trend_filter,
            trend_scale=spec.trend_scale,
            trend_gate=spec.trend_gate,
            hold_rank_buffer=spec.hold_rank_buffer,
            min_trade_weight=spec.min_trade_weight,
            max_new_positions=spec.max_new_positions,
            score_smoothing_observations=spec.score_smoothing_observations,
            score_smoothing_step_days=spec.score_smoothing_step_days,
        ),
        CandidateStressScenario(
            name="wider_basket",
            n_holdings=wider_holdings,
            max_weight=min(spec.max_weight, 0.03),
            rebalance=spec.rebalance,
            trend_filter=spec.trend_filter,
            trend_scale=spec.trend_scale,
            trend_gate=spec.trend_gate,
            hold_rank_buffer=spec.hold_rank_buffer,
            min_trade_weight=spec.min_trade_weight,
            max_new_positions=spec.max_new_positions,
            score_smoothing_observations=spec.score_smoothing_observations,
            score_smoothing_step_days=spec.score_smoothing_step_days,
        ),
        CandidateStressScenario(
            name="lower_concentration",
            n_holdings=spec.n_holdings,
            max_weight=max(0.01, spec.max_weight * 0.70),
            rebalance=spec.rebalance,
            trend_filter=spec.trend_filter,
            trend_scale=spec.trend_scale,
            trend_gate=spec.trend_gate,
            hold_rank_buffer=spec.hold_rank_buffer,
            min_trade_weight=spec.min_trade_weight,
            max_new_positions=spec.max_new_positions,
            score_smoothing_observations=spec.score_smoothing_observations,
            score_smoothing_step_days=spec.score_smoothing_step_days,
        ),
        CandidateStressScenario(
            name="rebalance_alt",
            n_holdings=spec.n_holdings,
            max_weight=spec.max_weight,
            rebalance=alt_rebalance,
            trend_filter=spec.trend_filter,
            trend_scale=spec.trend_scale,
            trend_gate=spec.trend_gate,
            hold_rank_buffer=spec.hold_rank_buffer,
            min_trade_weight=spec.min_trade_weight,
            max_new_positions=spec.max_new_positions,
            score_smoothing_observations=spec.score_smoothing_observations,
            score_smoothing_step_days=spec.score_smoothing_step_days,
        ),
        CandidateStressScenario(
            name="turnover_control",
            n_holdings=spec.n_holdings,
            max_weight=spec.max_weight,
            rebalance=spec.rebalance,
            trend_filter=spec.trend_filter,
            trend_scale=spec.trend_scale,
            trend_gate=spec.trend_gate,
            hold_rank_buffer=max(5, int(spec.n_holdings * 0.50)),
            min_trade_weight=0.01,
            max_new_positions=spec.max_new_positions,
            score_smoothing_observations=spec.score_smoothing_observations,
            score_smoothing_step_days=spec.score_smoothing_step_days,
        ),
        CandidateStressScenario(
            name="stability_control",
            n_holdings=spec.n_holdings,
            max_weight=spec.max_weight,
            rebalance=spec.rebalance,
            trend_filter=spec.trend_filter,
            trend_scale=spec.trend_scale,
            trend_gate=spec.trend_gate,
            hold_rank_buffer=max(10, int(spec.n_holdings)),
            min_trade_weight=0.02,
            max_new_positions=max(1, int(spec.n_holdings * 0.20)),
            score_smoothing_observations=spec.score_smoothing_observations,
            score_smoothing_step_days=spec.score_smoothing_step_days,
        ),
        CandidateStressScenario(
            name="score_smoothing",
            n_holdings=spec.n_holdings,
            max_weight=spec.max_weight,
            rebalance=spec.rebalance,
            trend_filter=spec.trend_filter,
            trend_scale=spec.trend_scale,
            trend_gate=spec.trend_gate,
            hold_rank_buffer=spec.hold_rank_buffer,
            min_trade_weight=spec.min_trade_weight,
            max_new_positions=spec.max_new_positions,
            score_smoothing_observations=max(3, spec.score_smoothing_observations),
            score_smoothing_step_days=20,
        ),
        CandidateStressScenario(
            name="high_cost",
            n_holdings=spec.n_holdings,
            max_weight=spec.max_weight,
            rebalance=spec.rebalance,
            cost_multiplier=2.0,
            trend_filter=spec.trend_filter,
            trend_scale=spec.trend_scale,
            trend_gate=spec.trend_gate,
            hold_rank_buffer=spec.hold_rank_buffer,
            min_trade_weight=spec.min_trade_weight,
            max_new_positions=spec.max_new_positions,
            score_smoothing_observations=spec.score_smoothing_observations,
            score_smoothing_step_days=spec.score_smoothing_step_days,
        ),
        *[
            CandidateStressScenario(
                name=f"small_capital_{slippage_bps}bps",
                n_holdings=spec.n_holdings,
                max_weight=spec.max_weight,
                rebalance=spec.rebalance,
                trend_filter=spec.trend_filter,
                trend_scale=spec.trend_scale,
                trend_gate=spec.trend_gate,
                hold_rank_buffer=spec.hold_rank_buffer,
                min_trade_weight=spec.min_trade_weight,
                max_new_positions=spec.max_new_positions,
                score_smoothing_observations=spec.score_smoothing_observations,
                score_smoothing_step_days=spec.score_smoothing_step_days,
                initial_cash=100_000.0,
                commission_rate=0.00025,
                min_commission=5.0,
                stamp_tax=0.0005,
                slippage_bps=float(slippage_bps),
                lot_size=100,
            )
            for slippage_bps in (5, 10, 20)
        ],
    ]
    if spec.trend_filter:
        scenarios.extend(
            [
                CandidateStressScenario(
                    name="trend_filter_off",
                    n_holdings=spec.n_holdings,
                    max_weight=spec.max_weight,
                    rebalance=spec.rebalance,
                    trend_filter=False,
                    trend_scale=spec.trend_scale,
                    trend_gate=spec.trend_gate,
                    hold_rank_buffer=spec.hold_rank_buffer,
                    min_trade_weight=spec.min_trade_weight,
                    max_new_positions=spec.max_new_positions,
                    score_smoothing_observations=spec.score_smoothing_observations,
                    score_smoothing_step_days=spec.score_smoothing_step_days,
                ),
                CandidateStressScenario(
                    name="trend_filter_stronger",
                    n_holdings=spec.n_holdings,
                    max_weight=spec.max_weight,
                    rebalance=spec.rebalance,
                    trend_filter=True,
                    trend_scale=max(0.0, min(spec.trend_scale * 0.60, 0.20)),
                    trend_gate=spec.trend_gate,
                    hold_rank_buffer=spec.hold_rank_buffer,
                    min_trade_weight=spec.min_trade_weight,
                    max_new_positions=spec.max_new_positions,
                    score_smoothing_observations=spec.score_smoothing_observations,
                    score_smoothing_step_days=spec.score_smoothing_step_days,
                ),
            ]
        )
    return scenarios


def run_candidate_stress_matrix(
    data: DataProvider,
    cfg,
    *,
    specs: list[CandidateSpec] | None = None,
    scenarios_by_candidate: dict[str, list[CandidateStressScenario]] | None = None,
    market_regime_by_candidate: dict[str, dict[str, Any]] | None = None,
) -> CandidateStressMatrixReport:
    candidates = specs or default_candidate_specs(cfg)
    results = []
    for spec in candidates:
        scenarios = (scenarios_by_candidate or {}).get(
            spec.name,
            default_candidate_stress_scenarios(spec),
        )
        results.extend(
            _run_candidate_scenario(
                data,
                cfg,
                spec,
                scenario,
                market_regime=(market_regime_by_candidate or {}).get(spec.name),
            )
            for scenario in scenarios
        )
    summaries = [_summary(spec.name, [row for row in results if row.candidate == spec.name]) for spec in candidates]
    stress_status = _combine_status([summary.status for summary in summaries])
    return CandidateStressMatrixReport(
        status=REPORT_STATUS,
        promotion_decision=PROMOTION_DECISION,
        stress_status=stress_status,
        candidate_count=len(candidates),
        scenario_count=len(results),
        summaries=summaries,
        results=results,
        missing_promotion_evidence=list(MISSING_PROMOTION_EVIDENCE),
        allowed_actions=list(ALLOWED_ACTIONS),
        prohibited_actions=list(PROHIBITED_ACTIONS),
    )


def write_candidate_stress_matrix_report(
    report: CandidateStressMatrixReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "candidate_stress_matrix.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "candidate_stress_matrix.md").write_text(report.to_markdown(), encoding="utf-8")
    _write_csv(root / "candidate_stress_matrix.csv", report.to_csv_rows())
    return root


def select_candidate_stress_scenarios(
    spec: CandidateSpec,
    names: list[str] | None,
) -> list[CandidateStressScenario]:
    scenarios = default_candidate_stress_scenarios(spec)
    if not names:
        return scenarios
    wanted = {name for name in names if name}
    selected = [scenario for scenario in scenarios if scenario.name in wanted]
    missing = sorted(wanted - {scenario.name for scenario in scenarios})
    if missing:
        available = ", ".join(scenario.name for scenario in scenarios)
        raise ValueError(f"Unknown stress scenario(s): {', '.join(missing)}. Available: {available}")
    if not selected:
        raise ValueError("No stress scenarios selected.")
    return selected


def _run_candidate_scenario(
    data: DataProvider,
    cfg,
    spec: CandidateSpec,
    scenario: CandidateStressScenario,
    market_regime: dict[str, Any] | None = None,
) -> CandidateStressResult:
    pipeline = FactorPipeline(factors=spec.factors)
    universe_filter = UniverseFilter(
        UniverseConfig(
            mode=cfg.universe.mode,
            index_code=cfg.universe.index_code,
            include_st=cfg.universe.include_st,
            min_history_days=cfg.universe.min_history_days,
        )
    )
    strategy_config = MultiFactorStrategyConfig(
        n_holdings=scenario.n_holdings,
        max_weight=scenario.max_weight,
        hold_rank_buffer=scenario.hold_rank_buffer,
        min_trade_weight=scenario.min_trade_weight,
        max_new_positions=scenario.max_new_positions,
        score_smoothing_observations=scenario.score_smoothing_observations,
        score_smoothing_step_days=scenario.score_smoothing_step_days,
    )
    strategy: MultiFactorTargetStrategy
    if scenario.trend_filter:
        scenario_market_regime = market_regime or runtime_market_regime(data, as_of=cfg.research.end)
        strategy = TrendFilteredTargetStrategy(
            universe_filter,
            pipeline,
            strategy_config,
            trend_scale=scenario.trend_scale,
            trend_gate=scenario.trend_gate,
            market_regime=scenario_market_regime,
        )
    else:
        strategy = MultiFactorTargetStrategy(universe_filter, pipeline, strategy_config)
    initial_cash = float(scenario.initial_cash or cfg.research.initial_cash)
    commission_rate = (
        float(scenario.commission_rate)
        if scenario.commission_rate is not None
        else float(cfg.broker.commission_rate) * scenario.cost_multiplier
    )
    min_commission = (
        float(scenario.min_commission)
        if scenario.min_commission is not None
        else float(cfg.broker.min_commission)
    )
    stamp_tax = (
        float(scenario.stamp_tax)
        if scenario.stamp_tax is not None
        else float(cfg.broker.stamp_tax) * scenario.cost_multiplier
    )
    slippage_bps = (
        float(scenario.slippage_bps)
        if scenario.slippage_bps is not None
        else float(cfg.broker.slippage_bps) * scenario.cost_multiplier
    )
    lot_size = int(scenario.lot_size or cfg.broker.lot_size)
    if scenario.cost_multiplier > 1:
        commission_rate = max(commission_rate, 0.00025)
        min_commission = max(min_commission, 5.0)
        stamp_tax = max(stamp_tax, 0.0005)
        slippage_bps = max(slippage_bps, 10.0)
    broker = PaperBroker(
        PaperBrokerConfig(
            commission_rate=commission_rate,
            min_commission=min_commission,
            stamp_tax=stamp_tax,
            slippage_bps=slippage_bps,
            price_limit_pct=cfg.broker.price_limit_pct,
            lot_size=lot_size,
        )
    )
    engine = ResearchEngine(
        data,
        strategy,
        broker,
        Portfolio(initial_cash=initial_cash),
        pipeline,
        max_drawdown_stop=cfg.risk.max_drawdown_stop,
    )
    result = engine.run(cfg.research.start, cfg.research.end, rebalance=scenario.rebalance)
    metrics = compute_report(
        result.equity_curve,
        result.fills,
        initial_equity=initial_cash,
    ).to_dict()
    order_count = len(result.orders)
    reject_count = sum(1 for order in result.orders if order.status == "rejected")
    reject_rate = reject_count / order_count if order_count else 0.0
    below_lot_reject_count = sum(
        1 for order in result.orders if order.status == "rejected" and order.reason == "below_lot"
    )
    min_commission_hit_count = sum(
        1
        for fill in result.fills
        if min_commission > 0 and abs(float(fill.commission) - min_commission) <= 1e-9
    )
    final_equity = float(metrics.get("final_equity", 0.0) or 0.0)
    final_cash_ratio = float(result.portfolio.cash) / final_equity if final_equity > 0 else 0.0
    turnover_summary = summarize_turnover(result.turnover)
    avg_turnover = float(turnover_summary["avg_turnover_pct"])
    avg_maintenance_turnover = float(turnover_summary["avg_maintenance_turnover_pct"])
    maintenance_turnover_count = int(turnover_summary["maintenance_turnover_observation_count"])
    notes = _scenario_notes(
        metrics,
        reject_rate,
        avg_turnover,
        avg_maintenance_turnover=avg_maintenance_turnover,
        maintenance_turnover_count=maintenance_turnover_count,
    )
    return CandidateStressResult(
        candidate=spec.name,
        scenario=scenario.name,
        status=_scenario_status(
            metrics,
            reject_rate,
            avg_turnover,
            avg_maintenance_turnover=avg_maintenance_turnover,
            maintenance_turnover_count=maintenance_turnover_count,
        ),
        parameters={
            **scenario.to_dict(),
            "effective_initial_cash": initial_cash,
            "effective_commission_rate": commission_rate,
            "effective_min_commission": min_commission,
            "effective_stamp_tax": stamp_tax,
            "effective_slippage_bps": slippage_bps,
            "effective_lot_size": lot_size,
        },
        metrics=metrics,
        order_count=order_count,
        reject_rate=reject_rate,
        execution_initial_cash=initial_cash,
        final_cash_ratio=final_cash_ratio,
        min_commission_hit_count=min_commission_hit_count,
        below_lot_reject_count=below_lot_reject_count,
        avg_turnover_pct=avg_turnover,
        initial_turnover_pct=float(turnover_summary["initial_turnover_pct"]),
        avg_maintenance_turnover_pct=avg_maintenance_turnover,
        max_maintenance_turnover_pct=float(turnover_summary["max_maintenance_turnover_pct"]),
        maintenance_turnover_observation_count=maintenance_turnover_count,
        trend_filter_active_days=int(getattr(strategy, "active_days", 0)),
        notes=notes,
    )


def _scenario_status(
    metrics: dict[str, float | int],
    reject_rate: float,
    avg_turnover: float,
    *,
    avg_maintenance_turnover: float,
    maintenance_turnover_count: int,
) -> StressStatus:
    if float(metrics.get("max_drawdown", 0.0)) >= 0.25 or reject_rate >= 0.50:
        return "BLOCK"
    if float(metrics.get("total_return", 0.0)) <= 0:
        return "WATCH"
    if float(metrics.get("sharpe_ratio", 0.0)) < 0.50:
        return "WATCH"
    if float(metrics.get("max_drawdown", 0.0)) >= 0.15:
        return "WATCH"
    if reject_rate >= 0.20:
        return "WATCH"
    if maintenance_turnover_count == 0 and avg_turnover >= 0.80:
        return "WATCH"
    if avg_maintenance_turnover >= 0.50 or avg_turnover >= 1.20:
        return "WATCH"
    return "PASS"


def _scenario_notes(
    metrics: dict[str, float | int],
    reject_rate: float,
    avg_turnover: float,
    *,
    avg_maintenance_turnover: float,
    maintenance_turnover_count: int,
) -> list[str]:
    notes = []
    if float(metrics.get("total_return", 0.0)) <= 0:
        notes.append("Non-positive return after configured costs.")
    if float(metrics.get("sharpe_ratio", 0.0)) < 0.50:
        notes.append("Risk-adjusted return is weak.")
    if float(metrics.get("max_drawdown", 0.0)) >= 0.15:
        notes.append("Drawdown is elevated for a small-capital compounding path.")
    if reject_rate >= 0.20:
        notes.append("Order rejection rate is high.")
    if maintenance_turnover_count == 0 and avg_turnover >= 0.80:
        notes.append("Only initial deployment turnover is observed; maintenance turnover is not proven.")
    elif avg_maintenance_turnover >= 0.50:
        notes.append("Maintenance turnover is high for small-capital compounding.")
    elif avg_turnover >= 0.80:
        notes.append("Total average turnover is high including initial deployment.")
    return notes or ["Scenario stayed inside basic research stress thresholds."]


def _summary(candidate: str, results: list[CandidateStressResult]) -> CandidateStressSummary:
    statuses = [result.status for result in results]
    metrics = [result.metrics for result in results]
    baseline = next((row for row in results if row.scenario == "baseline"), None)
    findings = []
    if not results:
        findings.append("No stress scenarios were generated.")
    if statuses.count("PASS") == 0 and results:
        findings.append("No stress scenario reached PASS.")
    if any(result.scenario == "high_cost" and result.status != "PASS" for result in results):
        findings.append("High-cost stress did not pass.")
    if any(result.avg_maintenance_turnover_pct >= 0.50 for result in results):
        findings.append("At least one scenario has high maintenance turnover.")
    elif any(
        result.maintenance_turnover_observation_count == 0 and result.avg_turnover_pct >= 0.80
        for result in results
    ):
        findings.append("At least one scenario only observes high initial deployment turnover.")
    if any(float(result.metrics.get("total_return", 0.0)) <= 0 for result in results):
        findings.append("At least one scenario has non-positive return.")
    return CandidateStressSummary(
        candidate=candidate,
        status=_combine_status(statuses),
        scenario_count=len(results),
        pass_count=statuses.count("PASS"),
        watch_count=statuses.count("WATCH"),
        block_count=statuses.count("BLOCK"),
        baseline_total_return=float((baseline.metrics if baseline else {}).get("total_return", 0.0)),
        worst_total_return=min((float(row.get("total_return", 0.0)) for row in metrics), default=0.0),
        worst_max_drawdown=max((float(row.get("max_drawdown", 0.0)) for row in metrics), default=0.0),
        worst_sharpe_ratio=min((float(row.get("sharpe_ratio", 0.0)) for row in metrics), default=0.0),
        max_reject_rate=max((result.reject_rate for result in results), default=0.0),
        max_turnover_pct=max((result.avg_turnover_pct for result in results), default=0.0),
        max_maintenance_turnover_pct=max(
            (result.max_maintenance_turnover_pct for result in results),
            default=0.0,
        ),
        findings=findings or ["All generated scenarios stayed inside basic research stress thresholds."],
    )


def _combine_status(statuses: list[StressStatus]) -> StressStatus:
    if not statuses or any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    if any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "candidate",
        "scenario",
        "status",
        "total_return",
        "annualized_return",
        "max_drawdown",
        "sharpe_ratio",
        "reject_rate",
        "execution_initial_cash",
        "final_cash_ratio",
        "min_commission_hit_count",
        "below_lot_reject_count",
        "avg_turnover_pct",
        "initial_turnover_pct",
        "avg_maintenance_turnover_pct",
        "max_maintenance_turnover_pct",
        "maintenance_turnover_observation_count",
        "trend_filter_active_days",
        "n_holdings",
        "max_weight",
        "rebalance",
        "cost_multiplier",
        "trend_filter",
        "trend_scale",
        "trend_gate",
        "hold_rank_buffer",
        "min_trade_weight",
        "max_new_positions",
        "score_smoothing_observations",
        "score_smoothing_step_days",
        "notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
