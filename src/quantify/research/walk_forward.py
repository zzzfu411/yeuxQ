"""Selection-safe walk-forward validation for the baseline strategy."""
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
    SELECTION_PROTOCOL,
    SELECTION_SCHEMA_VERSION,
    WALK_FORWARD_ARTIFACT,
    WalkForwardFold,
    WalkForwardMode,
    build_walk_forward_folds,
    protocol_configuration,
)

WalkForwardStatus = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class _PhaseResult:
    status: WalkForwardStatus
    metrics: dict[str, float | int]
    order_count: int
    reject_rate: float
    notes: list[str]


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    fold: WalkForwardFold
    status: WalkForwardStatus
    train_status: WalkForwardStatus
    selection_status: WalkForwardStatus
    test_status: WalkForwardStatus
    train_metrics: dict[str, float | int]
    selection_metrics: dict[str, float | int]
    metrics: dict[str, float | int]
    order_count: int
    reject_rate: float
    notes: list[str]

    @property
    def name(self) -> str:
        return self.fold.name

    @property
    def start(self) -> str:
        return self.fold.test.start

    @property
    def end(self) -> str:
        return self.fold.test.end

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "start": self.start,
            "end": self.end,
            "status": self.status,
            "train_status": self.train_status,
            "selection_status": self.selection_status,
            "test_status": self.test_status,
            "phases": self.fold.to_dict(),
            "train_metrics": self.train_metrics,
            "selection_metrics": self.selection_metrics,
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
    configuration: dict[str, str | int]
    schema_version: int = SELECTION_SCHEMA_VERSION
    selection_protocol: str = SELECTION_PROTOCOL
    selection_safe: bool = True
    test_used_for_selection: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": WALK_FORWARD_ARTIFACT,
            "schema_version": self.schema_version,
            "selection_protocol": self.selection_protocol,
            "selection_safe": self.selection_safe,
            "test_used_for_selection": self.test_used_for_selection,
            "selection_decision": "baseline_configuration_locked_before_test",
            "configuration": self.configuration,
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
            f"- Selection protocol: `{self.selection_protocol}`",
            f"- Selection safe: `{self.selection_safe}`",
            f"- Mode: `{self.configuration['mode']}`",
            f"- Windows: {self.window_count}",
            f"- PASS/WATCH/BLOCK: {self.pass_count}/{self.watch_count}/{self.block_count}",
            "- Test observations used for selection: `false`",
            "",
            "## Warnings",
        ]
        lines.extend(f"- {warning}" for warning in self.warnings) if self.warnings else lines.append("- None.")
        lines.extend(["", "## Windows", ""])
        lines.append(
            "| window | status | train | selection | test | train_status | "
            "selection_status | test_status | total_return | max_drawdown | sharpe | reject_rate |"
        )
        lines.append(
            "| --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |"
        )
        for window in self.windows:
            metrics = window.metrics
            lines.append(
                "| {name} | `{status}` | {train} | {selection} | {test} | `{train_status}` | "
                "`{selection_status}` | `{test_status}` | {ret:.2%} | {dd:.2%} | "
                "{sharpe:.2f} | {reject:.2%} |".format(
                    name=window.name,
                    status=window.status,
                    train=_range_label(window.fold.train.start, window.fold.train.end),
                    selection=_range_label(window.fold.selection.start, window.fold.selection.end),
                    test=_range_label(window.start, window.end),
                    train_status=window.train_status,
                    selection_status=window.selection_status,
                    test_status=window.test_status,
                    ret=float(metrics.get("total_return", 0.0)),
                    dd=float(metrics.get("max_drawdown", 0.0)),
                    sharpe=float(metrics.get("sharpe_ratio", 0.0)),
                    reject=window.reject_rate,
                )
            )
        lines.extend(
            [
                "",
                "The baseline configuration is fixed before each test window. "
                "Test results can only downgrade its evidence status.",
            ]
        )
        return "\n".join(lines) + "\n"


def run_walk_forward(
    data: DataProvider,
    cfg,
    *,
    train_days: int = 120,
    purge_days: int = 5,
    selection_days: int = 20,
    embargo_days: int = 5,
    test_days: int = 60,
    step_days: int = 60,
    mode: WalkForwardMode = "expanding",
) -> WalkForwardReport:
    days = data.trading_days(cfg.research.start, cfg.research.end)
    folds = build_walk_forward_folds(
        days,
        train_days=train_days,
        purge_days=purge_days,
        selection_days=selection_days,
        embargo_days=embargo_days,
        test_days=test_days,
        step_days=step_days,
        mode=mode,
    )
    windows = [_run_fold(data, cfg, fold) for fold in folds]
    warnings = _warnings(windows)
    return WalkForwardReport(
        status=_combine([window.status for window in windows], warnings),
        window_count=len(windows),
        pass_count=sum(1 for window in windows if window.status == "PASS"),
        watch_count=sum(1 for window in windows if window.status == "WATCH"),
        block_count=sum(1 for window in windows if window.status == "BLOCK"),
        windows=windows,
        warnings=warnings,
        configuration=protocol_configuration(
            train_days=train_days,
            purge_days=purge_days,
            selection_days=selection_days,
            embargo_days=embargo_days,
            test_days=test_days,
            step_days=step_days,
            mode=mode,
        ),
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


def _run_fold(data: DataProvider, cfg, fold: WalkForwardFold) -> WalkForwardWindow:
    train = _run_phase(data, cfg, fold.train.start, fold.train.end)
    selection = _run_phase(data, cfg, fold.selection.start, fold.selection.end)
    test = _run_phase(data, cfg, fold.test.start, fold.test.end)
    pretest_status = _worse_status(train.status, selection.status)
    status = _worse_status(pretest_status, test.status)
    notes = [
        f"Train evidence: {note}" for note in train.notes
    ] + [
        f"Selection evidence: {note}" for note in selection.notes
    ] + test.notes
    return WalkForwardWindow(
        fold=fold,
        status=status,
        train_status=train.status,
        selection_status=selection.status,
        test_status=test.status,
        train_metrics=train.metrics,
        selection_metrics=selection.metrics,
        metrics=test.metrics,
        order_count=test.order_count,
        reject_rate=test.reject_rate,
        notes=notes,
    )


def _run_phase(data: DataProvider, cfg, start: str, end: str) -> _PhaseResult:
    pipeline = FactorPipeline()
    strategy = MultiFactorTargetStrategy(
        UniverseFilter(
            UniverseConfig(
                mode=cfg.universe.mode,
                index_code=cfg.universe.index_code,
                include_st=cfg.universe.include_st,
                min_history_days=cfg.universe.min_history_days,
            )
        ),
        pipeline,
        MultiFactorStrategyConfig(
            n_holdings=cfg.strategy.n_holdings,
            max_weight=cfg.strategy.max_weight,
        ),
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
    result = ResearchEngine(
        data,
        strategy,
        broker,
        Portfolio(initial_cash=cfg.research.initial_cash),
        pipeline,
        max_drawdown_stop=cfg.risk.max_drawdown_stop,
    ).run(start, end, rebalance=cfg.research.rebalance)
    metrics = compute_report(
        result.equity_curve,
        result.fills,
        initial_equity=result.portfolio.initial_cash,
    ).to_dict()
    order_count = len(result.orders)
    reject_count = sum(1 for order in result.orders if order.status == "rejected")
    reject_rate = reject_count / order_count if order_count else 0.0
    return _PhaseResult(
        status=_window_status(metrics, reject_rate),
        metrics=metrics,
        order_count=order_count,
        reject_rate=reject_rate,
        notes=_notes(metrics, reject_rate),
    )


def _window_status(
    metrics: dict[str, float | int],
    reject_rate: float,
) -> WalkForwardStatus:
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
        notes.append("Non-positive return in this phase.")
    if float(metrics.get("max_drawdown", 0.0)) >= 0.15:
        notes.append("Drawdown is elevated in this phase.")
    if float(metrics.get("sharpe_ratio", 0.0)) < 0.5:
        notes.append("Sharpe is weak in this phase.")
    if reject_rate >= 0.20:
        notes.append("Order reject rate is high in this phase.")
    return notes


def _warnings(windows: list[WalkForwardWindow]) -> list[str]:
    if not windows:
        return ["No selection-safe walk-forward folds could be formed from the date range."]
    warnings = []
    bad = [window.name for window in windows if window.status != "PASS"]
    if bad:
        warnings.append(f"{len(bad)} walk-forward folds were not PASS: {', '.join(bad[:6])}.")
    if len(windows) < 3:
        warnings.append("Fewer than 3 selection-safe folds; stability evidence is weak.")
    return warnings


def _combine(
    statuses: list[WalkForwardStatus],
    warnings: list[str],
) -> WalkForwardStatus:
    if not statuses or any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    if any(status == "WATCH" for status in statuses) or warnings:
        return "WATCH"
    return "PASS"


def _worse_status(left: WalkForwardStatus, right: WalkForwardStatus) -> WalkForwardStatus:
    rank = {"PASS": 0, "WATCH": 1, "BLOCK": 2}
    return left if rank[left] >= rank[right] else right


def _range_label(start: str, end: str) -> str:
    return f"{start}..{end}" if start and end else "empty"
