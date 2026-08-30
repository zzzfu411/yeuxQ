"""Selection-safe walk-forward validation across strategy candidates."""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
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
from quantify.research.universe import UniverseConfig, UniverseFilter
from quantify.research.walk_forward_protocol import (
    CANDIDATE_WALK_FORWARD_ARTIFACT,
    SELECTION_PROTOCOL,
    SELECTION_SCHEMA_VERSION,
    WalkForwardFold,
    WalkForwardMode,
    WalkForwardPhase,
    build_walk_forward_folds,
    protocol_configuration,
)

CandidateWalkForwardStatus = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class _PhaseResult:
    status: CandidateWalkForwardStatus
    metrics: dict[str, float | int]
    reject_rate: float
    trend_filter_active_days: int
    notes: list[str]


@dataclass(frozen=True, slots=True)
class CandidateSelectionEvaluation:
    candidate: str
    window: str
    fold: WalkForwardFold
    rank: int
    train_status: CandidateWalkForwardStatus
    selection_status: CandidateWalkForwardStatus
    pretest_status: CandidateWalkForwardStatus
    train_metrics: dict[str, float | int]
    selection_metrics: dict[str, float | int]
    train_reject_rate: float
    selection_reject_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "window": self.window,
            "rank": self.rank,
            "train_status": self.train_status,
            "selection_status": self.selection_status,
            "pretest_status": self.pretest_status,
            "phases": self.fold.to_dict(),
            "train_metrics": self.train_metrics,
            "selection_metrics": self.selection_metrics,
            "train_reject_rate": self.train_reject_rate,
            "selection_reject_rate": self.selection_reject_rate,
        }


@dataclass(frozen=True, slots=True)
class CandidateWalkForwardWindow:
    candidate: str
    window: str
    fold: WalkForwardFold
    selection_rank: int
    selection_status: CandidateWalkForwardStatus
    test_status: CandidateWalkForwardStatus
    status: CandidateWalkForwardStatus
    metrics: dict[str, float | int]
    reject_rate: float
    trend_filter_active_days: int
    notes: list[str]

    @property
    def start(self) -> str:
        return self.fold.test.start

    @property
    def end(self) -> str:
        return self.fold.test.end

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "window": self.window,
            "start": self.start,
            "end": self.end,
            "selection_rank": self.selection_rank,
            "selection_status": self.selection_status,
            "test_status": self.test_status,
            "status": self.status,
            "phases": self.fold.to_dict(),
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
    selection_count: int
    selection_ratio: float
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
            "selection_count": self.selection_count,
            "selection_ratio": self.selection_ratio,
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
    selection_consistency_ratio: float
    summaries: list[CandidateWalkForwardSummary]
    selections: list[CandidateSelectionEvaluation]
    windows: list[CandidateWalkForwardWindow]
    warnings: list[str]
    configuration: dict[str, str | int]
    schema_version: int = SELECTION_SCHEMA_VERSION
    selection_protocol: str = SELECTION_PROTOCOL
    selection_safe: bool = True
    test_used_for_selection: bool = False

    @property
    def selected_candidate(self) -> str:
        return self.best_candidate

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": CANDIDATE_WALK_FORWARD_ARTIFACT,
            "schema_version": self.schema_version,
            "selection_protocol": self.selection_protocol,
            "selection_safe": self.selection_safe,
            "test_used_for_selection": self.test_used_for_selection,
            "configuration": self.configuration,
            "status": self.status,
            "selected_candidate": self.selected_candidate,
            "best_candidate": self.best_candidate,
            "candidate_count": self.candidate_count,
            "window_count": self.window_count,
            "selection_consistency_ratio": self.selection_consistency_ratio,
            "warnings": self.warnings,
            "summaries": [summary.to_dict() for summary in self.summaries],
            "selections": [selection.to_dict() for selection in self.selections],
            "windows": [window.to_dict() for window in self.windows],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Candidate Walk-forward Report: {self.status}",
            "",
            f"- Selection protocol: `{self.selection_protocol}`",
            f"- Selection safe: `{self.selection_safe}`",
            f"- Selected candidate: `{self.selected_candidate or 'none'}`",
            f"- Latest-candidate selection consistency: {self.selection_consistency_ratio:.2%}",
            f"- Candidates: {self.candidate_count}",
            f"- Test folds: {self.window_count}",
            "- Test observations used for selection: `false`",
            "",
            "## Candidate Stability",
            "",
            "| candidate | status | selected | selection_ratio | tests | pass | watch | block | "
            "positive | worst_return | worst_drawdown | avg_return | avg_drawdown | avg_sharpe | "
            "avg_reject | trend_filter_days |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
            "---: | ---: | ---: | ---: | ---: |",
        ]
        for summary in self.summaries:
            lines.append(
                f"| {summary.candidate} | `{summary.status}` | {summary.selection_count} | "
                f"{summary.selection_ratio:.2%} | {summary.window_count} | {summary.pass_count} | "
                f"{summary.watch_count} | {summary.block_count} | "
                f"{summary.positive_return_ratio:.2%} | {summary.worst_total_return:.2%} | "
                f"{summary.worst_max_drawdown:.2%} | {summary.avg_total_return:.2%} | "
                f"{summary.avg_max_drawdown:.2%} | {summary.avg_sharpe_ratio:.2f} | "
                f"{summary.avg_reject_rate:.2%} | {summary.trend_filter_active_days} |"
            )
        lines.extend(["", "## Locked Test Decisions", ""])
        lines.append(
            "| fold | selected_before_test | pretest_status | test_status | final_status | test |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for window in self.windows:
            lines.append(
                f"| {window.window} | `{window.candidate}` | `{window.selection_status}` | "
                f"`{window.test_status}` | `{window.status}` | {window.start}..{window.end} |"
            )
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in self.warnings) if self.warnings else lines.append("- None.")
        lines.extend(
            [
                "",
                "Each candidate is locked from train and selection evidence before its test begins. "
                "A test failure can downgrade that candidate, but cannot replace it with a test winner.",
                "This is paper-research evidence, not a promise of profit or a live instruction.",
            ]
        )
        return "\n".join(lines) + "\n"


def run_candidate_walk_forward(
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
    max_windows: int | None = None,
    specs: list[CandidateSpec] | None = None,
    market_regime_by_window: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> CandidateWalkForwardReport:
    days = data.trading_days(cfg.research.start, cfg.research.end)
    all_folds = build_walk_forward_folds(
        days,
        train_days=train_days,
        purge_days=purge_days,
        selection_days=selection_days,
        embargo_days=embargo_days,
        test_days=test_days,
        step_days=step_days,
        mode=mode,
    )
    folds = _limit_folds(all_folds, max_windows=max_windows)
    candidates = specs or default_candidate_specs(cfg)
    selections: list[CandidateSelectionEvaluation] = []
    windows: list[CandidateWalkForwardWindow] = []
    for fold in folds:
        ranked = _rank_pretest_candidates(
            [
                _evaluate_candidate(data, cfg, spec, fold, market_regime_by_window)
                for spec in candidates
            ]
        )
        selections.extend(ranked)
        if not ranked:
            continue
        selected = ranked[0]
        spec = next(spec for spec in candidates if spec.name == selected.candidate)
        windows.append(
            _run_locked_test(
                data,
                cfg,
                spec,
                fold,
                selected,
                market_regime_by_window=market_regime_by_window,
            )
        )
    selected_candidate = windows[-1].candidate if windows else ""
    summaries = [
        _summary(
            spec.name,
            [row for row in windows if row.candidate == spec.name],
            fold_count=len(folds),
        )
        for spec in candidates
    ]
    summaries = sorted(
        summaries,
        key=lambda item: (item.candidate != selected_candidate, item.candidate),
    )
    consistency = _selection_consistency(windows, selected_candidate)
    warnings = _warnings(summaries, folds, selected_candidate, consistency)
    if max_windows is not None and len(all_folds) > len(folds):
        warnings.append(
            f"Walk-forward was limited to the latest {len(folds)} of {len(all_folds)} folds."
        )
    selected_summary = next(
        (summary for summary in summaries if summary.candidate == selected_candidate),
        None,
    )
    return CandidateWalkForwardReport(
        status=_overall_status(selected_summary, warnings),
        best_candidate=selected_candidate,
        candidate_count=len(candidates),
        window_count=len(folds),
        selection_consistency_ratio=consistency,
        summaries=summaries,
        selections=selections,
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
    (root / "candidate_walk_forward_report.md").write_text(
        report.to_markdown(),
        encoding="utf-8",
    )
    return root


def _evaluate_candidate(
    data: DataProvider,
    cfg,
    spec: CandidateSpec,
    fold: WalkForwardFold,
    market_regime_by_window: dict[tuple[str, str], dict[str, Any]] | None,
) -> CandidateSelectionEvaluation:
    train = _run_candidate_phase(
        data,
        cfg,
        spec,
        fold.train,
        market_regime=_phase_regime(market_regime_by_window, fold.train),
    )
    selection = _run_candidate_phase(
        data,
        cfg,
        spec,
        fold.selection,
        market_regime=_phase_regime(market_regime_by_window, fold.selection),
    )
    return CandidateSelectionEvaluation(
        candidate=spec.name,
        window=fold.name,
        fold=fold,
        rank=0,
        train_status=train.status,
        selection_status=selection.status,
        pretest_status=_worse_status(train.status, selection.status),
        train_metrics=train.metrics,
        selection_metrics=selection.metrics,
        train_reject_rate=train.reject_rate,
        selection_reject_rate=selection.reject_rate,
    )


def _rank_pretest_candidates(
    evaluations: list[CandidateSelectionEvaluation],
) -> list[CandidateSelectionEvaluation]:
    ordered = sorted(evaluations, key=_pretest_rank)
    return [replace(item, rank=index) for index, item in enumerate(ordered, start=1)]


def _pretest_rank(item: CandidateSelectionEvaluation) -> tuple[Any, ...]:
    metrics = item.selection_metrics
    train = item.train_metrics
    return (
        -_status_rank(item.pretest_status),
        -_status_rank(item.selection_status),
        -float(metrics.get("total_return", 0.0)),
        -float(metrics.get("sharpe_ratio", 0.0)),
        float(metrics.get("max_drawdown", 0.0)),
        item.selection_reject_rate,
        -float(train.get("total_return", 0.0)),
        item.candidate,
    )


def _run_locked_test(
    data: DataProvider,
    cfg,
    spec: CandidateSpec,
    fold: WalkForwardFold,
    selected: CandidateSelectionEvaluation,
    *,
    market_regime_by_window: dict[tuple[str, str], dict[str, Any]] | None,
) -> CandidateWalkForwardWindow:
    pretest_as_of = fold.embargo.end or fold.selection.end
    pretest_regime = _phase_regime(market_regime_by_window, fold.selection)
    if pretest_regime is None and spec.trend_filter:
        pretest_regime = runtime_market_regime(data, as_of=pretest_as_of)
    test = _run_candidate_phase(
        data,
        cfg,
        spec,
        fold.test,
        market_regime=pretest_regime,
    )
    final_status = _worse_status(selected.pretest_status, test.status)
    notes = list(test.notes)
    if final_status != selected.pretest_status:
        notes.append("The locked candidate was downgraded by its test result.")
    notes.append("Candidate identity was locked before the test window opened.")
    return CandidateWalkForwardWindow(
        candidate=spec.name,
        window=fold.name,
        fold=fold,
        selection_rank=selected.rank,
        selection_status=selected.pretest_status,
        test_status=test.status,
        status=final_status,
        metrics=test.metrics,
        reject_rate=test.reject_rate,
        trend_filter_active_days=test.trend_filter_active_days,
        notes=notes,
    )


def _run_candidate_phase(
    data: DataProvider,
    cfg,
    spec: CandidateSpec,
    phase: WalkForwardPhase,
    *,
    market_regime: dict[str, Any] | None,
) -> _PhaseResult:
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
        regime = market_regime or runtime_market_regime(data, as_of=phase.end)
        strategy = TrendFilteredTargetStrategy(
            universe_filter,
            pipeline,
            strategy_config,
            trend_scale=spec.trend_scale,
            trend_gate=spec.trend_gate,
            market_regime=regime,
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
    result = ResearchEngine(
        data,
        strategy,
        broker,
        Portfolio(initial_cash=cfg.research.initial_cash),
        pipeline,
        max_drawdown_stop=cfg.risk.max_drawdown_stop,
    ).run(phase.start, phase.end, rebalance=spec.rebalance)
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
        reject_rate=reject_rate,
        trend_filter_active_days=int(getattr(strategy, "active_days", 0)),
        notes=_notes(metrics, reject_rate),
    )


def _summary(
    candidate: str,
    windows: list[CandidateWalkForwardWindow],
    *,
    fold_count: int,
) -> CandidateWalkForwardSummary:
    statuses = [window.status for window in windows]
    notes = []
    if not windows:
        notes.append("Candidate was never selected before a test window.")
    elif statuses.count("PASS") / len(statuses) < 0.60:
        notes.append("Fewer than 60% of selected test folds are PASS.")
    positive_ratio = _positive_return_ratio(windows)
    worst_return = _worst(windows, "total_return")
    worst_drawdown = _best(windows, "max_drawdown")
    if windows and positive_ratio < 0.60:
        notes.append("Fewer than 60% of selected test folds have positive returns.")
    if windows and worst_return <= -0.05:
        notes.append("Worst selected test-fold return is below -5%.")
    if statuses.count("BLOCK"):
        notes.append("At least one locked test fold is BLOCK.")
    selection_count = len(windows)
    return CandidateWalkForwardSummary(
        candidate=candidate,
        status=_candidate_status(statuses),
        window_count=len(windows),
        pass_count=statuses.count("PASS"),
        watch_count=statuses.count("WATCH"),
        block_count=statuses.count("BLOCK"),
        selection_count=selection_count,
        selection_ratio=selection_count / fold_count if fold_count else 0.0,
        avg_total_return=_avg(windows, "total_return"),
        avg_max_drawdown=_avg(windows, "max_drawdown"),
        avg_sharpe_ratio=_avg(windows, "sharpe_ratio"),
        avg_reject_rate=sum(window.reject_rate for window in windows) / len(windows)
        if windows
        else 0.0,
        positive_return_ratio=positive_ratio,
        worst_total_return=worst_return,
        worst_max_drawdown=worst_drawdown,
        trend_filter_active_days=sum(window.trend_filter_active_days for window in windows),
        notes=notes,
    )


def _limit_folds(
    folds: list[WalkForwardFold],
    *,
    max_windows: int | None,
) -> list[WalkForwardFold]:
    if max_windows is None:
        return folds
    if max_windows <= 0:
        raise ValueError("max_windows must be positive when supplied.")
    return folds[-max_windows:]


def _window_status(
    metrics: dict[str, float | int],
    reject_rate: float,
) -> CandidateWalkForwardStatus:
    if float(metrics.get("max_drawdown", 0.0)) >= 0.25 or reject_rate >= 0.50:
        return "BLOCK"
    if float(metrics.get("total_return", 0.0)) <= 0:
        return "WATCH"
    if float(metrics.get("sharpe_ratio", 0.0)) < 0.5 or reject_rate >= 0.20:
        return "WATCH"
    return "PASS"


def _candidate_status(
    statuses: list[CandidateWalkForwardStatus],
) -> CandidateWalkForwardStatus:
    if not statuses or any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    pass_ratio = statuses.count("PASS") / len(statuses)
    if pass_ratio < 0.60 or any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"


def _overall_status(
    selected: CandidateWalkForwardSummary | None,
    warnings: list[str],
) -> CandidateWalkForwardStatus:
    if selected is None or selected.status == "BLOCK":
        return "BLOCK"
    if selected.status == "WATCH" or warnings:
        return "WATCH"
    return "PASS"


def _warnings(
    summaries: list[CandidateWalkForwardSummary],
    folds: list[WalkForwardFold],
    selected_candidate: str,
    consistency: float,
) -> list[str]:
    warnings = []
    if not folds:
        warnings.append("No selection-safe walk-forward folds could be formed from the date range.")
    if len(folds) < 3:
        warnings.append("Fewer than 3 selection-safe folds; candidate stability evidence is weak.")
    if folds and consistency < 0.60:
        warnings.append("The latest selected candidate was chosen in fewer than 60% of folds.")
    selected = next(
        (summary for summary in summaries if summary.candidate == selected_candidate),
        None,
    )
    if selected is not None and selected.window_count < 3:
        warnings.append("The latest selected candidate has fewer than 3 locked test observations.")
    return warnings


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


def _avg(windows: list[CandidateWalkForwardWindow], key: str) -> float:
    if not windows:
        return 0.0
    return sum(float(window.metrics.get(key, 0.0)) for window in windows) / len(windows)


def _positive_return_ratio(windows: list[CandidateWalkForwardWindow]) -> float:
    if not windows:
        return 0.0
    positives = sum(
        1 for window in windows if float(window.metrics.get("total_return", 0.0)) > 0
    )
    return positives / len(windows)


def _worst(windows: list[CandidateWalkForwardWindow], key: str) -> float:
    if not windows:
        return 0.0
    return min(float(window.metrics.get(key, 0.0)) for window in windows)


def _best(windows: list[CandidateWalkForwardWindow], key: str) -> float:
    if not windows:
        return 0.0
    return max(float(window.metrics.get(key, 0.0)) for window in windows)


def _status_rank(status: CandidateWalkForwardStatus) -> int:
    return {"PASS": 2, "WATCH": 1, "BLOCK": 0}[status]


def _worse_status(
    left: CandidateWalkForwardStatus,
    right: CandidateWalkForwardStatus,
) -> CandidateWalkForwardStatus:
    rank = {"PASS": 0, "WATCH": 1, "BLOCK": 2}
    return left if rank[left] >= rank[right] else right


def _selection_consistency(
    windows: list[CandidateWalkForwardWindow],
    selected_candidate: str,
) -> float:
    if not windows or not selected_candidate:
        return 0.0
    return sum(window.candidate == selected_candidate for window in windows) / len(windows)


def _phase_regime(
    regimes: dict[tuple[str, str], dict[str, Any]] | None,
    phase: WalkForwardPhase,
) -> dict[str, Any] | None:
    if not regimes:
        return None
    return regimes.get((phase.start, phase.end))
