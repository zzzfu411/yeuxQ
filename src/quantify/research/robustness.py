"""Robustness experiments for the multi-factor research workflow."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quantify.analytics.metrics import compute_report
from quantify.core.portfolio import Portfolio
from quantify.data.provider import DataProvider
from quantify.engine.paper_broker import PaperBroker, PaperBrokerConfig
from quantify.research.engine import ResearchEngine
from quantify.research.factors import FactorPipeline
from quantify.research.strategy import MultiFactorStrategyConfig, MultiFactorTargetStrategy
from quantify.research.universe import UniverseConfig, UniverseFilter
from quantify.research.walk_forward_protocol import (
    ROBUSTNESS_ARTIFACT,
    ROBUSTNESS_REQUIRED_SCENARIOS,
    ROBUSTNESS_SELECTION_PROTOCOL,
    SELECTION_SCHEMA_VERSION,
    WalkForwardFold,
    WalkForwardMode,
    build_walk_forward_folds,
    protocol_configuration,
)

RobustnessStatus = Literal["PASS", "WATCH", "BLOCK"]

MIN_PROMOTION_FOLDS = 3
HIGH_COST_COMMISSION_FLOOR = 0.0006
HIGH_COST_MIN_COMMISSION_FLOOR = 5.0
HIGH_COST_STAMP_TAX_FLOOR = 0.001
HIGH_COST_SLIPPAGE_BPS_FLOOR = 10.0


@dataclass(frozen=True, slots=True)
class RobustnessScenario:
    name: str
    n_holdings: int
    max_weight: float
    rebalance: str
    commission_rate: float
    min_commission: float
    stamp_tax: float
    slippage_bps: float

    def to_dict(self) -> dict[str, str | float | int]:
        return {
            "name": self.name,
            "n_holdings": self.n_holdings,
            "max_weight": self.max_weight,
            "rebalance": self.rebalance,
            "commission_rate": self.commission_rate,
            "min_commission": self.min_commission,
            "stamp_tax": self.stamp_tax,
            "slippage_bps": self.slippage_bps,
        }


@dataclass(frozen=True, slots=True)
class RobustnessScenarioResult:
    name: str
    status: RobustnessStatus
    metrics: dict[str, float | int]
    order_count: int
    reject_rate: float
    avg_turnover_pct: float
    notes: list[str]
    fold_count: int
    pass_count: int
    watch_count: int
    block_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "metrics": self.metrics,
            "order_count": self.order_count,
            "reject_rate": self.reject_rate,
            "avg_turnover_pct": self.avg_turnover_pct,
            "notes": self.notes,
            "fold_count": self.fold_count,
            "pass_count": self.pass_count,
            "watch_count": self.watch_count,
            "block_count": self.block_count,
        }


@dataclass(frozen=True, slots=True)
class RobustnessFoldResult:
    fold: WalkForwardFold
    status: RobustnessStatus
    scenarios: list[RobustnessScenarioResult]

    @property
    def name(self) -> str:
        return self.fold.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "start": self.fold.test.start,
            "end": self.fold.test.end,
            "status": self.status,
            "evaluation_phase": "test",
            "scenario_count": len(self.scenarios),
            "phases": self.fold.to_dict(),
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
        }


@dataclass(frozen=True, slots=True)
class RobustnessReport:
    status: RobustnessStatus
    scenarios: list[RobustnessScenarioResult]
    baseline: dict[str, float | int]
    baseline_scenario: str | None
    warnings: list[str]
    configuration: dict[str, str | int]
    folds: list[RobustnessFoldResult]
    scenario_matrix: list[RobustnessScenario]
    artifact_type: str = ROBUSTNESS_ARTIFACT
    schema_version: int = SELECTION_SCHEMA_VERSION
    selection_protocol: str = ROBUSTNESS_SELECTION_PROTOCOL
    test_used_for_selection: bool = False
    scenario_matrix_frozen: bool = True
    evidence_role: str = "promotion_candidate"

    @property
    def selection_safe(self) -> bool:
        names = {scenario.name for scenario in self.scenario_matrix}
        return bool(self.folds) and all(
            required in names for required in ROBUSTNESS_REQUIRED_SCENARIOS
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "schema_version": self.schema_version,
            "selection_protocol": self.selection_protocol,
            "selection_safe": self.selection_safe,
            "test_used_for_selection": self.test_used_for_selection,
            "scenario_matrix_frozen": self.scenario_matrix_frozen,
            "evidence_role": self.evidence_role,
            "status": self.status,
            "configuration": self.configuration,
            "fold_count": len(self.folds),
            "folds": [fold.to_dict() for fold in self.folds],
            "scenario_count": len(self.scenario_matrix),
            "scenario_matrix": [scenario.to_dict() for scenario in self.scenario_matrix],
            "baseline_scenario": self.baseline_scenario,
            "baseline": self.baseline,
            "warnings": self.warnings,
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Robustness Report: {self.status}",
            "",
            f"- Selection safe: `{str(self.selection_safe).lower()}`",
            f"- Selection protocol: `{self.selection_protocol}`",
            f"- Evidence role: `{self.evidence_role}`",
            "- Test used for selection: `false`",
            "- Scenario matrix frozen before test: `true`",
            f"- Complete test folds: {len(self.folds)}",
            f"- Baseline scenario: `{self.baseline_scenario or 'not included'}`",
            "",
            "## Baseline",
            "",
        ]
        lines.extend(f"- {key}: `{value}`" for key, value in self.baseline.items())
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in self.warnings) if self.warnings else lines.append("- None.")
        lines.extend(["", "## Scenarios", ""])
        lines.append(
            "| scenario | status | folds | pass | watch | block | total_return | "
            "max_drawdown | sharpe | reject_rate | turnover |"
        )
        lines.append(
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
        )
        for scenario in self.scenarios:
            metrics = scenario.metrics
            lines.append(
                "| {name} | {status} | {folds} | {passes} | {watches} | {blocks} | "
                "{ret:.2%} | {dd:.2%} | {sharpe:.2f} | {reject:.2%} | {turnover:.2%} |".format(
                    name=scenario.name,
                    status=scenario.status,
                    folds=scenario.fold_count,
                    passes=scenario.pass_count,
                    watches=scenario.watch_count,
                    blocks=scenario.block_count,
                    ret=float(metrics.get("total_return", 0.0)),
                    dd=float(metrics.get("max_drawdown", 0.0)),
                    sharpe=float(metrics.get("sharpe_ratio", 0.0)),
                    reject=scenario.reject_rate,
                    turnover=scenario.avg_turnover_pct,
                )
            )
        lines.extend(["", "## Test Folds", ""])
        lines.append("| fold | status | test | scenarios |")
        lines.append("| --- | --- | --- | ---: |")
        for fold in self.folds:
            lines.append(
                f"| {fold.name} | {fold.status} | {fold.fold.test.start}..{fold.fold.test.end} | "
                f"{len(fold.scenarios)} |"
            )
        lines.extend(
            [
                "",
                "Every frozen scenario is evaluated on every fold's test phase. "
                "Test outcomes never select or remove scenarios.",
            ]
        )
        return "\n".join(lines) + "\n"


def default_scenarios(cfg) -> list[RobustnessScenario]:
    base_holdings = int(cfg.strategy.n_holdings)
    base_weight = float(cfg.strategy.max_weight)
    base_rebalance = str(cfg.research.rebalance)
    weekly_or_monthly = "weekly" if base_rebalance.lower().startswith("month") else "monthly"
    return [
        _scenario("baseline", cfg, base_holdings, base_weight, base_rebalance, 1.0),
        _scenario("holdings_low", cfg, max(3, base_holdings // 2), base_weight, base_rebalance, 1.0),
        _scenario("holdings_high", cfg, max(base_holdings + 1, int(base_holdings * 1.5)), base_weight, base_rebalance, 1.0),
        _scenario("max_weight_low", cfg, base_holdings, max(0.01, base_weight * 0.5), base_rebalance, 1.0),
        _scenario("rebalance_alt", cfg, base_holdings, base_weight, weekly_or_monthly, 1.0),
        _scenario("high_cost", cfg, base_holdings, base_weight, base_rebalance, 2.0),
    ]


def run_robustness(
    data: DataProvider,
    cfg,
    scenarios: list[RobustnessScenario] | None = None,
    *,
    mode: WalkForwardMode = "expanding",
    train_days: int = 120,
    purge_days: int = 5,
    selection_days: int = 20,
    embargo_days: int = 5,
    test_days: int = 60,
    step_days: int = 60,
) -> RobustnessReport:
    # Freeze the complete matrix before any result can influence execution.
    frozen_scenarios = tuple(scenarios or default_scenarios(cfg))
    configuration = protocol_configuration(
        train_days=train_days,
        purge_days=purge_days,
        selection_days=selection_days,
        embargo_days=embargo_days,
        test_days=test_days,
        step_days=step_days,
        mode=mode,
    )
    folds = build_walk_forward_folds(
        data.trading_days(cfg.research.start, cfg.research.end),
        train_days=train_days,
        purge_days=purge_days,
        selection_days=selection_days,
        embargo_days=embargo_days,
        test_days=test_days,
        step_days=step_days,
        mode=mode,
    )
    fold_results = [_run_fold(data, cfg, fold, frozen_scenarios) for fold in folds]
    scenario_results = [
        _aggregate_scenario(
            scenario.name,
            [fold.scenarios[index] for fold in fold_results],
        )
        for index, scenario in enumerate(frozen_scenarios)
    ]
    warnings = _robustness_warnings(scenario_results)
    frozen_names = {scenario.name for scenario in frozen_scenarios}
    missing_required = [
        name for name in ROBUSTNESS_REQUIRED_SCENARIOS if name not in frozen_names
    ]
    if not folds:
        warnings.insert(0, "No complete selection-safe robustness fold could be formed.")
    elif len(folds) < MIN_PROMOTION_FOLDS:
        warnings.insert(
            0,
            f"Only {len(folds)} complete robustness folds are available; "
            f"at least {MIN_PROMOTION_FOLDS} are required for PASS.",
        )
    if missing_required:
        warnings.append(
            "Frozen matrix is missing required promotion scenarios: "
            + ", ".join(missing_required)
            + "."
        )
    baseline_result = next(
        (scenario for scenario in scenario_results if scenario.name == "baseline"),
        None,
    )
    if baseline_result is None:
        warnings.append("The baseline scenario was not included; baseline metrics are unavailable.")
    return RobustnessReport(
        status=_report_status(
            scenario_results,
            fold_count=len(folds),
            matrix_complete=not missing_required,
        ),
        scenarios=scenario_results,
        baseline=baseline_result.metrics if baseline_result is not None else {},
        baseline_scenario=baseline_result.name if baseline_result is not None else None,
        warnings=warnings,
        configuration=configuration,
        folds=fold_results,
        scenario_matrix=list(frozen_scenarios),
    )


def write_robustness_report(report: RobustnessReport, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "robustness_report.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "robustness_report.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _scenario(
    name: str,
    cfg,
    n_holdings: int,
    max_weight: float,
    rebalance: str,
    cost_multiplier: float,
) -> RobustnessScenario:
    commission_rate = float(cfg.broker.commission_rate) * cost_multiplier
    min_commission = float(cfg.broker.min_commission)
    stamp_tax = float(cfg.broker.stamp_tax) * cost_multiplier
    slippage_bps = float(cfg.broker.slippage_bps) * cost_multiplier
    if name == "high_cost":
        commission_rate = max(commission_rate, HIGH_COST_COMMISSION_FLOOR)
        min_commission = max(min_commission, HIGH_COST_MIN_COMMISSION_FLOOR)
        stamp_tax = max(stamp_tax, HIGH_COST_STAMP_TAX_FLOOR)
        slippage_bps = max(slippage_bps, HIGH_COST_SLIPPAGE_BPS_FLOOR)
    return RobustnessScenario(
        name=name,
        n_holdings=n_holdings,
        max_weight=max_weight,
        rebalance=rebalance,
        commission_rate=commission_rate,
        min_commission=min_commission,
        stamp_tax=stamp_tax,
        slippage_bps=slippage_bps,
    )


def _run_fold(
    data: DataProvider,
    cfg,
    fold: WalkForwardFold,
    scenarios: tuple[RobustnessScenario, ...],
) -> RobustnessFoldResult:
    results = [
        _run_scenario(
            data,
            cfg,
            scenario,
            start=fold.test.start,
            end=fold.test.end,
        )
        for scenario in scenarios
    ]
    return RobustnessFoldResult(
        fold=fold,
        status=_combine_status([result.status for result in results]),
        scenarios=results,
    )


def _run_scenario(
    data: DataProvider,
    cfg,
    scenario: RobustnessScenario,
    *,
    start: str,
    end: str,
) -> RobustnessScenarioResult:
    pipeline = FactorPipeline()
    universe_filter = UniverseFilter(
        UniverseConfig(
            mode=cfg.universe.mode,
            index_code=cfg.universe.index_code,
            include_st=cfg.universe.include_st,
            min_history_days=cfg.universe.min_history_days,
        )
    )
    strategy = MultiFactorTargetStrategy(
        universe_filter,
        pipeline,
        MultiFactorStrategyConfig(n_holdings=scenario.n_holdings, max_weight=scenario.max_weight),
    )
    broker = PaperBroker(
        PaperBrokerConfig(
            commission_rate=scenario.commission_rate,
            min_commission=scenario.min_commission,
            stamp_tax=scenario.stamp_tax,
            slippage_bps=scenario.slippage_bps,
            price_limit_pct=cfg.broker.price_limit_pct,
            lot_size=cfg.broker.lot_size,
        )
    )
    engine = ResearchEngine(
        data,
        strategy,
        broker,
        Portfolio(initial_cash=cfg.research.initial_cash),
        pipeline,
        max_drawdown_stop=cfg.risk.max_drawdown_stop,
    )
    result = engine.run(start, end, rebalance=scenario.rebalance)
    metrics = compute_report(
        result.equity_curve,
        result.fills,
        initial_equity=result.portfolio.initial_cash,
    ).to_dict()
    order_count = len(result.orders)
    reject_count = sum(1 for order in result.orders if order.status == "rejected")
    reject_rate = reject_count / order_count if order_count else 0.0
    turnover = [float(row.get("turnover_pct", 0.0)) for row in result.turnover]
    avg_turnover = sum(turnover) / len(turnover) if turnover else 0.0
    status = _scenario_status(metrics, reject_rate, avg_turnover)
    notes = _scenario_notes(metrics, reject_rate, avg_turnover)
    return RobustnessScenarioResult(
        name=scenario.name,
        status=status,
        metrics=metrics,
        order_count=order_count,
        reject_rate=reject_rate,
        avg_turnover_pct=avg_turnover,
        notes=notes,
        fold_count=1,
        pass_count=int(status == "PASS"),
        watch_count=int(status == "WATCH"),
        block_count=int(status == "BLOCK"),
    )


def _aggregate_scenario(
    name: str,
    fold_results: list[RobustnessScenarioResult],
) -> RobustnessScenarioResult:
    if not fold_results:
        return RobustnessScenarioResult(
            name=name,
            status="BLOCK",
            metrics={},
            order_count=0,
            reject_rate=0.0,
            avg_turnover_pct=0.0,
            notes=["No complete test fold was available for this scenario."],
            fold_count=0,
            pass_count=0,
            watch_count=0,
            block_count=0,
        )
    order_count = sum(result.order_count for result in fold_results)
    rejected_orders = sum(result.reject_rate * result.order_count for result in fold_results)
    statuses = [result.status for result in fold_results]
    notes = [
        f"{result.name} test fold {index} returned {result.status}."
        for index, result in enumerate(fold_results, start=1)
        if result.status != "PASS"
    ]
    return RobustnessScenarioResult(
        name=name,
        status=_combine_status(statuses),
        metrics=_aggregate_metrics([result.metrics for result in fold_results]),
        order_count=order_count,
        reject_rate=rejected_orders / order_count if order_count else 0.0,
        avg_turnover_pct=sum(result.avg_turnover_pct for result in fold_results)
        / len(fold_results),
        notes=notes,
        fold_count=len(fold_results),
        pass_count=sum(status == "PASS" for status in statuses),
        watch_count=sum(status == "WATCH" for status in statuses),
        block_count=sum(status == "BLOCK" for status in statuses),
    )


def _aggregate_metrics(
    metrics_by_fold: list[dict[str, float | int]],
) -> dict[str, float | int]:
    keys = sorted({key for metrics in metrics_by_fold for key in metrics})
    aggregate: dict[str, float | int] = {}
    for key in keys:
        values = [metrics[key] for metrics in metrics_by_fold if key in metrics]
        if key in {"n_bars", "n_round_trips"}:
            aggregate[key] = sum(int(value) for value in values)
        else:
            aggregate[key] = sum(float(value) for value in values) / len(values)
    return aggregate


def _scenario_status(
    metrics: dict[str, float | int],
    reject_rate: float,
    avg_turnover: float,
) -> RobustnessStatus:
    if float(metrics["max_drawdown"]) >= 0.25 or reject_rate >= 0.50:
        return "BLOCK"
    if float(metrics["total_return"]) <= 0 or float(metrics["sharpe_ratio"]) < 0.5:
        return "WATCH"
    if reject_rate >= 0.20 or avg_turnover >= 0.80:
        return "WATCH"
    return "PASS"


def _scenario_notes(
    metrics: dict[str, float | int],
    reject_rate: float,
    avg_turnover: float,
) -> list[str]:
    notes = []
    if float(metrics["total_return"]) <= 0:
        notes.append("Non-positive net return after costs.")
    if float(metrics["max_drawdown"]) >= 0.15:
        notes.append("Drawdown is near or above the watch threshold.")
    if float(metrics["sharpe_ratio"]) < 0.5:
        notes.append("Risk-adjusted return is weak.")
    if reject_rate >= 0.20:
        notes.append("Order rejection rate is high.")
    if avg_turnover >= 0.80:
        notes.append("Turnover is high.")
    return notes


def _robustness_warnings(results: list[RobustnessScenarioResult]) -> list[str]:
    warnings = []
    for result in results:
        if result.status != "PASS":
            warnings.append(f"{result.name} returned {result.status}.")
    return warnings


def _report_status(
    scenarios: list[RobustnessScenarioResult],
    *,
    fold_count: int,
    matrix_complete: bool,
) -> RobustnessStatus:
    status = _combine_status([scenario.status for scenario in scenarios])
    if fold_count == 0:
        return "BLOCK"
    if (fold_count < MIN_PROMOTION_FOLDS or not matrix_complete) and status == "PASS":
        return "WATCH"
    return status


def _combine_status(statuses: list[RobustnessStatus]) -> RobustnessStatus:
    if not statuses or any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    if any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"
