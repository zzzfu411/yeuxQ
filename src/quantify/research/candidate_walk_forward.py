"""Walk-forward validation across strategy candidates."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from quantify.analytics.metrics import compute_report
from quantify.core.portfolio import Portfolio
from quantify.data.provider import DataProvider
from quantify.engine.paper_broker import PaperBroker, PaperBrokerConfig
from quantify.research.candidates import CandidateSpec, TrendFilteredTargetStrategy, default_candidate_specs
from quantify.research.candidates import runtime_market_regime
from quantify.research.engine import ResearchEngine
from quantify.research.factors import FactorPipeline
from quantify.research.strategy import MultiFactorStrategyConfig, MultiFactorTargetStrategy
from quantify.research.universe import UniverseConfig, UniverseFilter

CandidateWalkForwardStatus = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class CandidateWalkForwardWindow:
    candidate: str
    window: str
    start: str
    end: str
    status: CandidateWalkForwardStatus
    metrics: dict[str, float | int]
    reject_rate: float
    trend_filter_active_days: int
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "window": self.window,
            "start": self.start,
            "end": self.end,
            "status": self.status,
            "metrics": self.metrics,
            "reject_rate": self.reject_rate,
            "trend_filter_active_days": self.trend_filter_active_days,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class CandidateWalkForwardSummary:
    candidate: str
    status: CandidateWalkForwardStatus
    window_count: int
    pass_count: int
    watch_count: int
    block_count: int
    avg_total_return: float
    avg_max_drawdown: float
    avg_sharpe_ratio: float
    avg_reject_rate: float
    positive_return_ratio: float
    worst_total_return: float
    worst_max_drawdown: float
    trend_filter_active_days: int
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "status": self.status,
            "window_count": self.window_count,
            "pass_count": self.pass_count,
            "watch_count": self.watch_count,
            "block_count": self.block_count,
            "avg_total_return": self.avg_total_return,
            "avg_max_drawdown": self.avg_max_drawdown,
            "avg_sharpe_ratio": self.avg_sharpe_ratio,
            "avg_reject_rate": self.avg_reject_rate,
            "positive_return_ratio": self.positive_return_ratio,
            "worst_total_return": self.worst_total_return,
            "worst_max_drawdown": self.worst_max_drawdown,
            "trend_filter_active_days": self.trend_filter_active_days,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class CandidateWalkForwardReport:
    status: CandidateWalkForwardStatus
    best_candidate: str
    candidate_count: int
    window_count: int
    summaries: list[CandidateWalkForwardSummary]
    windows: list[CandidateWalkForwardWindow]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "best_candidate": self.best_candidate,
            "candidate_count": self.candidate_count,
            "window_count": self.window_count,
            "warnings": self.warnings,
            "summaries": [summary.to_dict() for summary in self.summaries],
            "windows": [window.to_dict() for window in self.windows],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Candidate Walk-forward Report: {self.status}",
            "",
            f"- Best candidate: `{self.best_candidate or 'none'}`",
            f"- Candidates: {self.candidate_count}",
            f"- Windows per candidate: {self.window_count}",
            "",
            "## Candidate Stability",
            "",
            "| candidate | status | windows | pass | watch | block | positive | worst_return | worst_drawdown | avg_return | avg_drawdown | avg_sharpe | avg_reject | trend_filter_days |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for summary in self.summaries:
            lines.append(
                "| {candidate} | `{status}` | {windows} | {passes} | {watch} | {block} | {positive:.2%} | {worst_ret:.2%} | {worst_dd:.2%} | {ret:.2%} | {dd:.2%} | {sharpe:.2f} | {reject:.2%} | {trend_days} |".format(
                    candidate=summary.candidate,
                    status=summary.status,
                    windows=summary.window_count,
                    passes=summary.pass_count,
                    watch=summary.watch_count,
                    block=summary.block_count,
                    positive=summary.positive_return_ratio,
                    worst_ret=summary.worst_total_return,
                    worst_dd=summary.worst_max_drawdown,
                    ret=summary.avg_total_return,
                    dd=summary.avg_max_drawdown,
                    sharpe=summary.avg_sharpe_ratio,
                    reject=summary.avg_reject_rate,
                    trend_days=summary.trend_filter_active_days,
                )
            )
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in self.warnings) if self.warnings else lines.append("- None.")
        lines.extend(
            [
                "",
                "This is stability evidence for paper research, not a promise of profit or a live trading instruction.",
            ]
        )
        return "\n".join(lines) + "\n"


def run_candidate_walk_forward(
    data: DataProvider,
    cfg,
    *,
    train_days: int = 120,
    test_days: int = 60,
    step_days: int = 60,
    max_windows: int | None = None,
    specs: list[CandidateSpec] | None = None,
    market_regime_by_window: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> CandidateWalkForwardReport:
    days = data.trading_days(cfg.research.start, cfg.research.end)
    all_window_ranges = _windows(days, train_days=train_days, test_days=test_days, step_days=step_days)
    window_ranges = _limit_windows(all_window_ranges, max_windows=max_windows)
    candidates = specs or default_candidate_specs(cfg)
    windows: list[CandidateWalkForwardWindow] = []
    for spec in candidates:
        for idx, (start, end) in enumerate(window_ranges, start=1):
            windows.append(
                _run_candidate_window(
                    data,
                    cfg,
                    spec,
                    idx,
                    start,
                    end,
                    market_regime=(market_regime_by_window or {}).get((start, end)),
                )
            )
    summaries = [_summary(spec.name, [row for row in windows if row.candidate == spec.name]) for spec in candidates]
    summaries = sorted(summaries, key=_summary_rank, reverse=True)
    warnings = _warnings(summaries, window_ranges)
    if max_windows is not None and len(all_window_ranges) > len(window_ranges):
        warnings.append(
            f"Walk-forward was limited to the latest {len(window_ranges)} of {len(all_window_ranges)} windows."
        )
    return CandidateWalkForwardReport(
        status=_overall_status(summaries, warnings),
        best_candidate=summaries[0].candidate if summaries else "",
        candidate_count=len(candidates),
        window_count=len(window_ranges),
        summaries=summaries,
        windows=windows,
        warnings=warnings,
    )


def write_candidate_walk_forward_report(
    report: CandidateWalkForwardReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "candidate_walk_forward_report.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "candidate_walk_forward_report.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _run_candidate_window(
    data: DataProvider,
    cfg,
    spec: CandidateSpec,
    idx: int,
    start: str,
    end: str,
    market_regime: dict[str, Any] | None = None,
) -> CandidateWalkForwardWindow:
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
        n_holdings=spec.n_holdings,
        max_weight=spec.max_weight,
        hold_rank_buffer=spec.hold_rank_buffer,
        min_trade_weight=spec.min_trade_weight,
        max_new_positions=spec.max_new_positions,
        score_smoothing_observations=spec.score_smoothing_observations,
        score_smoothing_step_days=spec.score_smoothing_step_days,
    )
    strategy: MultiFactorTargetStrategy
    if spec.trend_filter:
        window_market_regime = market_regime or runtime_market_regime(data, as_of=end)
        strategy = TrendFilteredTargetStrategy(
            universe_filter,
            pipeline,
            strategy_config,
            trend_scale=spec.trend_scale,
            trend_gate=spec.trend_gate,
            market_regime=window_market_regime,
        )
    else:
        strategy = MultiFactorTargetStrategy(universe_filter, pipeline, strategy_config)
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
    result = engine.run(start, end, rebalance=spec.rebalance)
    metrics = compute_report(result.equity_curve, result.fills).to_dict()
    order_count = len(result.orders)
    reject_count = sum(1 for order in result.orders if order.status == "rejected")
    reject_rate = reject_count / order_count if order_count else 0.0
    status = _window_status(metrics, reject_rate)
    return CandidateWalkForwardWindow(
        candidate=spec.name,
        window=f"wf_{idx:02d}",
        start=start,
        end=end,
        status=status,
        metrics=metrics,
        reject_rate=reject_rate,
        trend_filter_active_days=int(getattr(strategy, "active_days", 0)),
        notes=_notes(metrics, reject_rate),
    )


def _summary(candidate: str, windows: list[CandidateWalkForwardWindow]) -> CandidateWalkForwardSummary:
    statuses = [window.status for window in windows]
    notes = []
    if not windows:
        notes.append("No walk-forward windows could be formed.")
    elif statuses.count("PASS") / len(statuses) < 0.60:
        notes.append("Fewer than 60% of windows are PASS.")
    positive_ratio = _positive_return_ratio(windows)
    worst_return = _worst(windows, "total_return")
    worst_drawdown = _best(windows, "max_drawdown")
    if windows and positive_ratio < 0.60:
        notes.append("Fewer than 60% of forward windows have positive returns.")
    if windows and worst_return <= -0.05:
        notes.append("Worst forward-window return is below -5%.")
    if statuses.count("BLOCK"):
        notes.append("At least one forward window is BLOCK.")
    return CandidateWalkForwardSummary(
        candidate=candidate,
        status=_candidate_status(statuses),
        window_count=len(windows),
        pass_count=statuses.count("PASS"),
        watch_count=statuses.count("WATCH"),
        block_count=statuses.count("BLOCK"),
        avg_total_return=_avg(windows, "total_return"),
        avg_max_drawdown=_avg(windows, "max_drawdown"),
        avg_sharpe_ratio=_avg(windows, "sharpe_ratio"),
        avg_reject_rate=sum(window.reject_rate for window in windows) / len(windows) if windows else 0.0,
        positive_return_ratio=positive_ratio,
        worst_total_return=worst_return,
        worst_max_drawdown=worst_drawdown,
        trend_filter_active_days=sum(window.trend_filter_active_days for window in windows),
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


def _limit_windows(
    window_ranges: list[tuple[str, str]],
    *,
    max_windows: int | None,
) -> list[tuple[str, str]]:
    if max_windows is None:
        return window_ranges
    if max_windows <= 0:
        raise ValueError("max_windows must be positive when supplied.")
    return window_ranges[-max_windows:]


def _window_status(metrics: dict[str, float | int], reject_rate: float) -> CandidateWalkForwardStatus:
    if float(metrics.get("max_drawdown", 0.0)) >= 0.25 or reject_rate >= 0.50:
        return "BLOCK"
    if float(metrics.get("total_return", 0.0)) <= 0:
        return "WATCH"
    if float(metrics.get("sharpe_ratio", 0.0)) < 0.5 or reject_rate >= 0.20:
        return "WATCH"
    return "PASS"


def _candidate_status(statuses: list[CandidateWalkForwardStatus]) -> CandidateWalkForwardStatus:
    if not statuses or any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    pass_ratio = statuses.count("PASS") / len(statuses)
    if pass_ratio < 0.60 or any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"


def _overall_status(
    summaries: list[CandidateWalkForwardSummary],
    warnings: list[str],
) -> CandidateWalkForwardStatus:
    if any(summary.status == "PASS" for summary in summaries) and not warnings:
        return "PASS"
    if any(summary.status in {"PASS", "WATCH"} for summary in summaries):
        return "WATCH"
    return "BLOCK"


def _warnings(
    summaries: list[CandidateWalkForwardSummary],
    window_ranges: list[tuple[str, str]],
) -> list[str]:
    warnings = []
    if not window_ranges:
        warnings.append("No walk-forward windows could be formed from the configured date range.")
    if len(window_ranges) < 3:
        warnings.append("Fewer than 3 windows; candidate stability evidence is weak.")
    if summaries and not any(summary.status == "PASS" for summary in summaries):
        warnings.append("No candidate passed walk-forward stability thresholds.")
    return warnings


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


def _avg(windows: list[CandidateWalkForwardWindow], key: str) -> float:
    if not windows:
        return 0.0
    return sum(float(window.metrics.get(key, 0.0)) for window in windows) / len(windows)


def _positive_return_ratio(windows: list[CandidateWalkForwardWindow]) -> float:
    if not windows:
        return 0.0
    positives = sum(1 for window in windows if float(window.metrics.get("total_return", 0.0)) > 0)
    return positives / len(windows)


def _worst(windows: list[CandidateWalkForwardWindow], key: str) -> float:
    if not windows:
        return 0.0
    return min(float(window.metrics.get(key, 0.0)) for window in windows)


def _best(windows: list[CandidateWalkForwardWindow], key: str) -> float:
    if not windows:
        return 0.0
    return max(float(window.metrics.get(key, 0.0)) for window in windows)


def _summary_rank(summary: CandidateWalkForwardSummary) -> tuple[int, int, float, float, float, float]:
    rank = {"PASS": 2, "WATCH": 1, "BLOCK": 0}[summary.status]
    return (
        rank,
        summary.pass_count,
        summary.positive_return_ratio,
        summary.worst_total_return,
        -summary.worst_max_drawdown,
        summary.avg_sharpe_ratio,
    )
