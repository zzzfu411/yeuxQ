"""Regime-stratified validation for strategy candidates."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from quantify.data.provider import DataProvider
from quantify.market import detect_market_regime
from quantify.research.candidate_walk_forward import (
    CandidateWalkForwardReport,
    CandidateWalkForwardWindow,
    run_candidate_walk_forward,
)
from quantify.research.candidates import CandidateSpec

CandidateRegimeStatus = Literal["PASS", "WATCH", "BLOCK"]

ADVERSE_REGIMES = {"defensive", "risk_off"}


@dataclass(frozen=True, slots=True)
class CandidateRegimeWindow:
    candidate: str
    window: str
    start: str
    end: str
    regime_label: str
    regime_status: str
    strategy_status: CandidateRegimeStatus
    metrics: dict[str, float | int]
    reject_rate: float
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "window": self.window,
            "start": self.start,
            "end": self.end,
            "regime_label": self.regime_label,
            "regime_status": self.regime_status,
            "strategy_status": self.strategy_status,
            "metrics": self.metrics,
            "reject_rate": self.reject_rate,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class CandidateRegimeBucket:
    candidate: str
    regime_label: str
    status: CandidateRegimeStatus
    window_count: int
    pass_count: int
    watch_count: int
    block_count: int
    avg_total_return: float
    avg_max_drawdown: float
    avg_sharpe_ratio: float
    avg_reject_rate: float
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "regime_label": self.regime_label,
            "status": self.status,
            "window_count": self.window_count,
            "pass_count": self.pass_count,
            "watch_count": self.watch_count,
            "block_count": self.block_count,
            "avg_total_return": self.avg_total_return,
            "avg_max_drawdown": self.avg_max_drawdown,
            "avg_sharpe_ratio": self.avg_sharpe_ratio,
            "avg_reject_rate": self.avg_reject_rate,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class CandidateRegimeSummary:
    candidate: str
    status: CandidateRegimeStatus
    regime_count: int
    known_regime_count: int
    adverse_regime_window_count: int
    pass_bucket_count: int
    watch_bucket_count: int
    block_bucket_count: int
    avg_total_return: float
    avg_max_drawdown: float
    avg_sharpe_ratio: float
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "status": self.status,
            "regime_count": self.regime_count,
            "known_regime_count": self.known_regime_count,
            "adverse_regime_window_count": self.adverse_regime_window_count,
            "pass_bucket_count": self.pass_bucket_count,
            "watch_bucket_count": self.watch_bucket_count,
            "block_bucket_count": self.block_bucket_count,
            "avg_total_return": self.avg_total_return,
            "avg_max_drawdown": self.avg_max_drawdown,
            "avg_sharpe_ratio": self.avg_sharpe_ratio,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class CandidateRegimeValidationReport:
    status: CandidateRegimeStatus
    best_candidate: str
    candidate_count: int
    window_count: int
    regime_count: int
    warnings: list[str]
    summaries: list[CandidateRegimeSummary]
    buckets: list[CandidateRegimeBucket]
    windows: list[CandidateRegimeWindow]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "best_candidate": self.best_candidate,
            "candidate_count": self.candidate_count,
            "window_count": self.window_count,
            "regime_count": self.regime_count,
            "warnings": self.warnings,
            "summaries": [summary.to_dict() for summary in self.summaries],
            "buckets": [bucket.to_dict() for bucket in self.buckets],
            "windows": [window.to_dict() for window in self.windows],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Candidate Regime Validation: {self.status}",
            "",
            f"- Best candidate: `{self.best_candidate or 'none'}`",
            f"- Candidates: {self.candidate_count}",
            f"- Windows: {self.window_count}",
            f"- Regimes: {self.regime_count}",
            "",
            "## Candidate Regime Summary",
            "",
            "| candidate | status | regimes | known_regimes | adverse_windows | pass_buckets | watch_buckets | block_buckets | avg_return | avg_drawdown | avg_sharpe |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for summary in self.summaries:
            lines.append(
                "| {candidate} | `{status}` | {regimes} | {known} | {adverse} | {passes} | {watch} | {block} | {ret:.2%} | {dd:.2%} | {sharpe:.2f} |".format(
                    candidate=summary.candidate,
                    status=summary.status,
                    regimes=summary.regime_count,
                    known=summary.known_regime_count,
                    adverse=summary.adverse_regime_window_count,
                    passes=summary.pass_bucket_count,
                    watch=summary.watch_bucket_count,
                    block=summary.block_bucket_count,
                    ret=summary.avg_total_return,
                    dd=summary.avg_max_drawdown,
                    sharpe=summary.avg_sharpe_ratio,
                )
            )
        lines.extend(["", "## Regime Buckets", ""])
        lines.append(
            "| candidate | regime | status | windows | pass | watch | block | avg_return | avg_drawdown | avg_sharpe | avg_reject |"
        )
        lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for bucket in self.buckets:
            lines.append(
                "| {candidate} | `{regime}` | `{status}` | {windows} | {passes} | {watch} | {block} | {ret:.2%} | {dd:.2%} | {sharpe:.2f} | {reject:.2%} |".format(
                    candidate=bucket.candidate,
                    regime=bucket.regime_label,
                    status=bucket.status,
                    windows=bucket.window_count,
                    passes=bucket.pass_count,
                    watch=bucket.watch_count,
                    block=bucket.block_count,
                    ret=bucket.avg_total_return,
                    dd=bucket.avg_max_drawdown,
                    sharpe=bucket.avg_sharpe_ratio,
                    reject=bucket.avg_reject_rate,
                )
            )
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in self.warnings) if self.warnings else lines.append("- None.")
        lines.append("")
        lines.append(
            "This report is stability evidence for research and paper review, not a promise of profit or a live trading instruction."
        )
        return "\n".join(lines) + "\n"


def run_candidate_regime_validation(
    data: DataProvider,
    cfg,
    *,
    train_days: int = 120,
    test_days: int = 60,
    step_days: int = 60,
    max_windows: int | None = None,
    specs: list[CandidateSpec] | None = None,
    candidate_walk_forward: CandidateWalkForwardReport | None = None,
    market_regime_by_window: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> CandidateRegimeValidationReport:
    walk_forward = candidate_walk_forward or run_candidate_walk_forward(
        data,
        cfg,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
        max_windows=max_windows,
        specs=specs,
        market_regime_by_window=market_regime_by_window,
    )
    regimes = _window_regimes(
        data,
        walk_forward.windows,
        market_regime_by_window=market_regime_by_window,
    )
    windows = [
        _regime_window(window, regimes.get((window.start, window.end), {}))
        for window in walk_forward.windows
    ]
    buckets = _buckets(windows)
    summaries = _summaries(buckets)
    warnings = _warnings(summaries, windows)
    return CandidateRegimeValidationReport(
        status=_overall_status(summaries, warnings),
        best_candidate=summaries[0].candidate if summaries else "",
        candidate_count=walk_forward.candidate_count,
        window_count=walk_forward.window_count,
        regime_count=len({window.regime_label for window in windows if window.regime_label != "unknown"}),
        warnings=warnings,
        summaries=summaries,
        buckets=buckets,
        windows=windows,
    )


def write_candidate_regime_validation_report(
    report: CandidateRegimeValidationReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "candidate_regime_validation_report.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "candidate_regime_validation_report.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _window_regimes(
    data: DataProvider,
    windows: list[CandidateWalkForwardWindow],
    market_regime_by_window: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    ranges = sorted({(window.start, window.end) for window in windows})
    return {
        item: (market_regime_by_window or {}).get(item)
        or detect_market_regime(
            data,
            item[0],
            item[1],
            min_history_days=_window_min_history_days(data, item[0], item[1]),
        ).to_dict()
        for item in ranges
    }


def _window_min_history_days(data: DataProvider, start: str, end: str) -> int:
    days = data.trading_days(start, end)
    if not days:
        return 20
    return max(20, min(60, len(days)))


def _regime_window(
    window: CandidateWalkForwardWindow,
    regime: dict[str, Any],
) -> CandidateRegimeWindow:
    label = str(regime.get("label", "unknown"))
    regime_status = str(regime.get("status", "UNKNOWN"))
    notes = list(window.notes)
    if label == "unknown" or regime_status == "WATCH":
        notes.append("Market regime evidence for this window is weak or defensive.")
    if label in ADVERSE_REGIMES:
        notes.append("This is an adverse-market validation window.")
    return CandidateRegimeWindow(
        candidate=window.candidate,
        window=window.window,
        start=window.start,
        end=window.end,
        regime_label=label,
        regime_status=regime_status,
        strategy_status=window.status,
        metrics=window.metrics,
        reject_rate=window.reject_rate,
        notes=notes,
    )


def _buckets(windows: list[CandidateRegimeWindow]) -> list[CandidateRegimeBucket]:
    keys = sorted({(window.candidate, window.regime_label) for window in windows})
    buckets = [_bucket(candidate, regime, [w for w in windows if (w.candidate, w.regime_label) == (candidate, regime)]) for candidate, regime in keys]
    return sorted(buckets, key=lambda row: (row.candidate, _regime_rank(row.regime_label)))


def _bucket(
    candidate: str,
    regime_label: str,
    windows: list[CandidateRegimeWindow],
) -> CandidateRegimeBucket:
    statuses = [window.strategy_status for window in windows]
    notes = []
    avg_return = _avg_metric(windows, "total_return")
    avg_drawdown = _avg_metric(windows, "max_drawdown")
    avg_sharpe = _avg_metric(windows, "sharpe_ratio")
    avg_reject = sum(window.reject_rate for window in windows) / len(windows) if windows else 0.0
    if regime_label == "unknown":
        notes.append("Regime label is unknown; collect more broad-market data.")
    if statuses.count("PASS") / len(statuses) < 0.60 if statuses else True:
        notes.append("Fewer than 60% of windows are PASS in this regime bucket.")
    if avg_return <= 0 and windows:
        notes.append("Average return is non-positive in this regime bucket.")
    status = _bucket_status(regime_label, statuses, avg_return, avg_drawdown, avg_reject)
    return CandidateRegimeBucket(
        candidate=candidate,
        regime_label=regime_label,
        status=status,
        window_count=len(windows),
        pass_count=statuses.count("PASS"),
        watch_count=statuses.count("WATCH"),
        block_count=statuses.count("BLOCK"),
        avg_total_return=avg_return,
        avg_max_drawdown=avg_drawdown,
        avg_sharpe_ratio=avg_sharpe,
        avg_reject_rate=avg_reject,
        notes=notes,
    )


def _summaries(buckets: list[CandidateRegimeBucket]) -> list[CandidateRegimeSummary]:
    candidates = sorted({bucket.candidate for bucket in buckets})
    summaries = [_summary(candidate, [bucket for bucket in buckets if bucket.candidate == candidate]) for candidate in candidates]
    return sorted(summaries, key=_summary_rank, reverse=True)


def _summary(candidate: str, buckets: list[CandidateRegimeBucket]) -> CandidateRegimeSummary:
    statuses = [bucket.status for bucket in buckets]
    known = [bucket for bucket in buckets if bucket.regime_label != "unknown"]
    adverse_windows = sum(bucket.window_count for bucket in buckets if bucket.regime_label in ADVERSE_REGIMES)
    notes = []
    if not buckets:
        notes.append("No regime buckets are available.")
    if len(known) < 2:
        notes.append("Fewer than 2 known regimes were observed.")
    if adverse_windows == 0:
        notes.append("No defensive or risk_off windows were observed; adverse-regime evidence is missing.")
    if statuses.count("BLOCK"):
        notes.append("At least one regime bucket is BLOCK.")
    return CandidateRegimeSummary(
        candidate=candidate,
        status=_summary_status(statuses, known_regime_count=len(known), adverse_window_count=adverse_windows),
        regime_count=len(buckets),
        known_regime_count=len(known),
        adverse_regime_window_count=adverse_windows,
        pass_bucket_count=statuses.count("PASS"),
        watch_bucket_count=statuses.count("WATCH"),
        block_bucket_count=statuses.count("BLOCK"),
        avg_total_return=_avg_bucket(buckets, "avg_total_return"),
        avg_max_drawdown=_avg_bucket(buckets, "avg_max_drawdown"),
        avg_sharpe_ratio=_avg_bucket(buckets, "avg_sharpe_ratio"),
        notes=notes,
    )


def _bucket_status(
    regime_label: str,
    statuses: list[CandidateRegimeStatus],
    avg_return: float,
    avg_drawdown: float,
    avg_reject_rate: float,
) -> CandidateRegimeStatus:
    if not statuses or any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    if avg_drawdown >= 0.25 or avg_reject_rate >= 0.50:
        return "BLOCK"
    pass_ratio = statuses.count("PASS") / len(statuses)
    if regime_label == "unknown" or pass_ratio < 0.60 or avg_return <= 0:
        return "WATCH"
    if any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"


def _summary_status(
    statuses: list[CandidateRegimeStatus],
    *,
    known_regime_count: int,
    adverse_window_count: int,
) -> CandidateRegimeStatus:
    if not statuses or any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    if known_regime_count < 2 or adverse_window_count == 0:
        return "WATCH"
    if any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"


def _overall_status(
    summaries: list[CandidateRegimeSummary],
    warnings: list[str],
) -> CandidateRegimeStatus:
    if any(summary.status == "PASS" for summary in summaries) and not warnings:
        return "PASS"
    if any(summary.status in {"PASS", "WATCH"} for summary in summaries):
        return "WATCH"
    return "BLOCK"


def _warnings(
    summaries: list[CandidateRegimeSummary],
    windows: list[CandidateRegimeWindow],
) -> list[str]:
    warnings = []
    if not windows:
        warnings.append("No candidate walk-forward windows are available for regime validation.")
    known_regimes = {window.regime_label for window in windows if window.regime_label != "unknown"}
    if len(known_regimes) < 2:
        warnings.append("Fewer than 2 known market regimes are represented in the validation windows.")
    if not any(window.regime_label in ADVERSE_REGIMES for window in windows):
        warnings.append("No defensive or risk_off validation windows are available.")
    if summaries and not any(summary.status == "PASS" for summary in summaries):
        warnings.append("No candidate passed regime-stratified validation thresholds.")
    return warnings


def _avg_metric(windows: list[CandidateRegimeWindow], key: str) -> float:
    return sum(float(window.metrics.get(key, 0.0)) for window in windows) / len(windows) if windows else 0.0


def _avg_bucket(buckets: list[CandidateRegimeBucket], key: str) -> float:
    return sum(float(getattr(bucket, key)) for bucket in buckets) / len(buckets) if buckets else 0.0


def _summary_rank(summary: CandidateRegimeSummary) -> tuple[int, int, int, float, float]:
    return (
        _status_rank(summary.status),
        summary.adverse_regime_window_count,
        summary.pass_bucket_count,
        summary.avg_total_return,
        summary.avg_sharpe_ratio,
    )


def _status_rank(status: CandidateRegimeStatus) -> int:
    return {"PASS": 2, "WATCH": 1, "BLOCK": 0}[status]


def _regime_rank(label: str) -> int:
    return {"risk_off": 0, "defensive": 1, "neutral": 2, "risk_on": 3, "unknown": 4}.get(label, 5)
