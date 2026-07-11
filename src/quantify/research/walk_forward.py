"""Walk-forward validation for the baseline multi-factor strategy."""
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

WalkForwardStatus = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    name: str
    start: str
    end: str
    status: WalkForwardStatus
    metrics: dict[str, float | int]
    order_count: int
    reject_rate: float
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "start": self.start,
            "end": self.end,
            "status": self.status,
            "metrics": self.metrics,
            "order_count": self.order_count,
            "reject_rate": self.reject_rate,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class WalkForwardReport:
    status: WalkForwardStatus
    window_count: int
    pass_count: int
    watch_count: int
    block_count: int
    windows: list[WalkForwardWindow]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "window_count": self.window_count,
            "pass_count": self.pass_count,
            "watch_count": self.watch_count,
            "block_count": self.block_count,
            "warnings": self.warnings,
            "windows": [window.to_dict() for window in self.windows],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Walk-forward Report: {self.status}",
            "",
            f"- Windows: {self.window_count}",
            f"- PASS/WATCH/BLOCK: {self.pass_count}/{self.watch_count}/{self.block_count}",
            "",
            "## Warnings",
        ]
        lines.extend(f"- {warning}" for warning in self.warnings) if self.warnings else lines.append("- None.")
        lines.extend(["", "## Windows", ""])
        lines.append("| window | status | start | end | total_return | max_drawdown | sharpe | reject_rate |")
        lines.append("| --- | --- | --- | --- | ---: | ---: | ---: | ---: |")
        for window in self.windows:
            metrics = window.metrics
            lines.append(
                "| {name} | `{status}` | {start} | {end} | {ret:.2%} | {dd:.2%} | {sharpe:.2f} | {reject:.2%} |".format(
                    name=window.name,
                    status=window.status,
                    start=window.start,
                    end=window.end,
                    ret=float(metrics.get("total_return", 0.0)),
                    dd=float(metrics.get("max_drawdown", 0.0)),
                    sharpe=float(metrics.get("sharpe_ratio", 0.0)),
                    reject=window.reject_rate,
                )
            )
        return "\n".join(lines) + "\n"


def run_walk_forward(
    data: DataProvider,
    cfg,
    *,
    train_days: int = 120,
    test_days: int = 60,
    step_days: int = 60,
) -> WalkForwardReport:
    days = data.trading_days(cfg.research.start, cfg.research.end)
    windows = [
        _run_window(data, cfg, idx, test_start, test_end)
        for idx, (test_start, test_end) in enumerate(
            _windows(days, train_days=train_days, test_days=test_days, step_days=step_days),
            start=1,
        )
    ]
    warnings = _warnings(windows)
    return WalkForwardReport(
        status=_combine([window.status for window in windows], warnings),
        window_count=len(windows),
        pass_count=sum(1 for window in windows if window.status == "PASS"),
        watch_count=sum(1 for window in windows if window.status == "WATCH"),
        block_count=sum(1 for window in windows if window.status == "BLOCK"),
        windows=windows,
        warnings=warnings,
    )


def write_walk_forward_report(report: WalkForwardReport, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "walk_forward_report.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "walk_forward_report.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _run_window(
    data: DataProvider,
    cfg,
    idx: int,
    start: str,
    end: str,
) -> WalkForwardWindow:
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
        MultiFactorStrategyConfig(n_holdings=cfg.strategy.n_holdings, max_weight=cfg.strategy.max_weight),
    )
    broker = PaperBroker(
        PaperBrokerConfig(
            commission_rate=cfg.broker.commission_rate,
            min_commission=cfg.broker.min_commission,
            stamp_tax=cfg.broker.stamp_tax,
            slippage_bps=cfg.broker.slippage_bps,
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
    result = engine.run(start, end, rebalance=cfg.research.rebalance)
    metrics = compute_report(result.equity_curve, result.fills).to_dict()
    order_count = len(result.orders)
    reject_count = sum(1 for order in result.orders if order.status == "rejected")
    reject_rate = reject_count / order_count if order_count else 0.0
    notes = _notes(metrics, reject_rate)
    return WalkForwardWindow(
        name=f"wf_{idx:02d}",
        start=start,
        end=end,
        status=_window_status(metrics, reject_rate),
        metrics=metrics,
        order_count=order_count,
        reject_rate=reject_rate,
        notes=notes,
    )


def _windows(
    days: list[str],
    *,
    train_days: int,
    test_days: int,
    step_days: int,
) -> list[tuple[str, str]]:
    out = []
    start_idx = train_days
    while start_idx + test_days <= len(days):
        test = days[start_idx : start_idx + test_days]
        if len(test) >= 2:
            out.append((test[0], test[-1]))
        start_idx += step_days
    return out


def _window_status(metrics: dict[str, float | int], reject_rate: float) -> WalkForwardStatus:
    if float(metrics.get("max_drawdown", 0.0)) >= 0.25 or reject_rate >= 0.50:
        return "BLOCK"
    if float(metrics.get("total_return", 0.0)) <= 0:
        return "WATCH"
    if float(metrics.get("sharpe_ratio", 0.0)) < 0.5 or reject_rate >= 0.20:
        return "WATCH"
    return "PASS"


def _notes(metrics: dict[str, float | int], reject_rate: float) -> list[str]:
    notes = []
    if float(metrics.get("total_return", 0.0)) <= 0:
        notes.append("Non-positive return in this forward window.")
    if float(metrics.get("max_drawdown", 0.0)) >= 0.15:
        notes.append("Drawdown is elevated in this forward window.")
    if float(metrics.get("sharpe_ratio", 0.0)) < 0.5:
        notes.append("Sharpe is weak in this forward window.")
    if reject_rate >= 0.20:
        notes.append("Order reject rate is high in this forward window.")
    return notes


def _warnings(windows: list[WalkForwardWindow]) -> list[str]:
    if not windows:
        return ["No walk-forward windows could be formed from the configured date range."]
    warnings = []
    bad = [window.name for window in windows if window.status != "PASS"]
    if bad:
        warnings.append(f"{len(bad)} walk-forward windows were not PASS: {', '.join(bad[:6])}.")
    if len(windows) < 3:
        warnings.append("Fewer than 3 walk-forward windows; stability evidence is weak.")
    return warnings


def _combine(statuses: list[WalkForwardStatus], warnings: list[str]) -> WalkForwardStatus:
    if not statuses or any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    if any(status == "WATCH" for status in statuses) or warnings:
        return "WATCH"
    return "PASS"
