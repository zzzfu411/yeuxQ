"""Robustness experiments for the multi-factor research workflow."""
from __future__ import annotations

from dataclasses import dataclass
import json
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

RobustnessStatus = Literal["PASS", "WATCH", "BLOCK"]


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


@dataclass(frozen=True, slots=True)
class RobustnessScenarioResult:
    name: str
    status: RobustnessStatus
    metrics: dict[str, float | int]
    order_count: int
    reject_rate: float
    avg_turnover_pct: float
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "metrics": self.metrics,
            "order_count": self.order_count,
            "reject_rate": self.reject_rate,
            "avg_turnover_pct": self.avg_turnover_pct,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class RobustnessReport:
    status: RobustnessStatus
    scenarios: list[RobustnessScenarioResult]
    baseline: dict[str, float | int]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "baseline": self.baseline,
            "warnings": self.warnings,
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Robustness Report: {self.status}",
            "",
            "## Baseline",
            "",
        ]
        lines.extend(f"- {key}: `{value}`" for key, value in self.baseline.items())
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in self.warnings) if self.warnings else lines.append("- None.")
        lines.extend(["", "## Scenarios", ""])
        lines.append("| scenario | status | total_return | max_drawdown | sharpe | reject_rate | turnover |")
        lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
        for scenario in self.scenarios:
            metrics = scenario.metrics
            lines.append(
                "| {name} | {status} | {ret:.2%} | {dd:.2%} | {sharpe:.2f} | {reject:.2%} | {turnover:.2%} |".format(
                    name=scenario.name,
                    status=scenario.status,
                    ret=float(metrics.get("total_return", 0.0)),
                    dd=float(metrics.get("max_drawdown", 0.0)),
                    sharpe=float(metrics.get("sharpe_ratio", 0.0)),
                    reject=scenario.reject_rate,
                    turnover=scenario.avg_turnover_pct,
                )
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


def run_robustness(data: DataProvider, cfg, scenarios: list[RobustnessScenario] | None = None) -> RobustnessReport:
    scenario_results = [_run_scenario(data, cfg, scenario) for scenario in (scenarios or default_scenarios(cfg))]
    baseline = scenario_results[0].metrics if scenario_results else {}
    warnings = _robustness_warnings(scenario_results)
    status = _combine_status([scenario.status for scenario in scenario_results])
    if warnings and status == "PASS":
        status = "WATCH"
    return RobustnessReport(status=status, scenarios=scenario_results, baseline=baseline, warnings=warnings)


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
    return RobustnessScenario(
        name=name,
        n_holdings=n_holdings,
        max_weight=max_weight,
        rebalance=rebalance,
        commission_rate=float(cfg.broker.commission_rate) * cost_multiplier,
        min_commission=float(cfg.broker.min_commission),
        stamp_tax=float(cfg.broker.stamp_tax) * cost_multiplier,
        slippage_bps=float(cfg.broker.slippage_bps) * cost_multiplier,
    )


def _run_scenario(data: DataProvider, cfg, scenario: RobustnessScenario) -> RobustnessScenarioResult:
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
    result = engine.run(cfg.research.start, cfg.research.end, rebalance=scenario.rebalance)
    metrics = compute_report(result.equity_curve, result.fills).to_dict()
    order_count = len(result.orders)
    reject_count = sum(1 for order in result.orders if order.status == "rejected")
    reject_rate = reject_count / order_count if order_count else 0.0
    turnover = [float(row.get("turnover_pct", 0.0)) for row in result.turnover]
    avg_turnover = sum(turnover) / len(turnover) if turnover else 0.0
    notes = _scenario_notes(metrics, reject_rate, avg_turnover)
    return RobustnessScenarioResult(
        name=scenario.name,
        status=_scenario_status(metrics, reject_rate, avg_turnover),
        metrics=metrics,
        order_count=order_count,
        reject_rate=reject_rate,
        avg_turnover_pct=avg_turnover,
        notes=notes,
    )


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


def _combine_status(statuses: list[RobustnessStatus]) -> RobustnessStatus:
    if any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    if any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"
