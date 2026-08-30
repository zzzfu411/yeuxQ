"""Dependency-light benchmark analytics for aligned daily return series.

The report status describes evidence completeness, not strategy quality. A PASS
does not imply that a strategy outperformed or is suitable for deployment.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil, sqrt
from typing import Any, Literal

import numpy as np
import pandas as pd

BenchmarkStatus = Literal["PASS", "WATCH", "BLOCK"]
SeriesKind = Literal["equity", "returns"]


@dataclass(frozen=True, slots=True)
class BenchmarkIdentity:
    """Human-readable identity and return convention for the benchmark."""

    symbol: str
    name: str
    total_return: bool

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "total_return": self.total_return,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkConfiguration:
    periods_per_year: int
    block_size: int
    n_bootstrap: int
    random_seed: int

    def to_dict(self) -> dict[str, int]:
        return {
            "periods_per_year": self.periods_per_year,
            "block_size": self.block_size,
            "n_bootstrap": self.n_bootstrap,
            "random_seed": self.random_seed,
        }


@dataclass(frozen=True, slots=True)
class AlignmentEvidence:
    strategy_input_observations: int
    benchmark_input_observations: int
    strategy_return_observations: int
    benchmark_return_observations: int
    aligned_observations: int
    strategy_unmatched_observations: int
    benchmark_unmatched_observations: int
    start_date: str | None
    end_date: str | None

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "strategy_input_observations": self.strategy_input_observations,
            "benchmark_input_observations": self.benchmark_input_observations,
            "strategy_return_observations": self.strategy_return_observations,
            "benchmark_return_observations": self.benchmark_return_observations,
            "aligned_observations": self.aligned_observations,
            "strategy_unmatched_observations": self.strategy_unmatched_observations,
            "benchmark_unmatched_observations": self.benchmark_unmatched_observations,
            "start_date": self.start_date,
            "end_date": self.end_date,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkMetrics:
    strategy_cagr: float | None
    benchmark_cagr: float | None
    excess_cagr: float | None
    annualized_excess_return: float | None
    annualized_tracking_error: float | None
    information_ratio: float | None

    def to_dict(self) -> dict[str, float | None]:
        return {
            "strategy_cagr": self.strategy_cagr,
            "benchmark_cagr": self.benchmark_cagr,
            "excess_cagr": self.excess_cagr,
            "annualized_excess_return": self.annualized_excess_return,
            "annualized_tracking_error": self.annualized_tracking_error,
            "information_ratio": self.information_ratio,
        }


@dataclass(frozen=True, slots=True)
class BootstrapConfidenceInterval:
    status: BenchmarkStatus
    lower: float | None
    upper: float | None
    confidence_level: float
    method: str
    samples_requested: int
    samples_used: int

    def to_dict(self) -> dict[str, str | float | int | None]:
        return {
            "status": self.status,
            "lower": self.lower,
            "upper": self.upper,
            "confidence_level": self.confidence_level,
            "method": self.method,
            "samples_requested": self.samples_requested,
            "samples_used": self.samples_used,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkAnalysis:
    status: BenchmarkStatus
    benchmark: BenchmarkIdentity
    strategy_series_kind: SeriesKind
    benchmark_series_kind: SeriesKind
    configuration: BenchmarkConfiguration
    alignment: AlignmentEvidence
    metrics: BenchmarkMetrics
    annualized_excess_return_ci: BootstrapConfidenceInterval
    information_ratio_ci: BootstrapConfidenceInterval
    findings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": "daily_benchmark_analysis",
            "schema_version": 1,
            "status": self.status,
            "benchmark": self.benchmark.to_dict(),
            "strategy_series_kind": self.strategy_series_kind,
            "benchmark_series_kind": self.benchmark_series_kind,
            "configuration": self.configuration.to_dict(),
            "alignment": self.alignment.to_dict(),
            "metrics": self.metrics.to_dict(),
            "annualized_excess_return_ci": self.annualized_excess_return_ci.to_dict(),
            "information_ratio_ci": self.information_ratio_ci.to_dict(),
            "findings": list(self.findings),
        }


def analyze_benchmark(
    strategy_series: pd.Series,
    benchmark_series: pd.Series,
    benchmark: BenchmarkIdentity,
    *,
    strategy_series_kind: SeriesKind = "equity",
    benchmark_series_kind: SeriesKind = "equity",
    periods_per_year: int = 252,
    block_size: int = 5,
    n_bootstrap: int = 1_000,
    random_seed: int = 0,
) -> BenchmarkAnalysis:
    """Compare strategy and benchmark series on their common return dates.

    Equity inputs are converted to percentage returns on their own date index
    before the two return series are inner-aligned. CAGR is geometric. Annualized
    excess return is the arithmetic mean of daily active returns multiplied by
    ``periods_per_year``; tracking error uses sample standard deviation, and the
    information ratio is their quotient. Bootstrap samples preserve local serial
    dependence by resampling overlapping, non-circular blocks of active returns.

    Invalid inputs and samples shorter than ``max(2, block_size)`` produce BLOCK
    evidence with unavailable metrics represented by ``None``.
    """
    configuration = BenchmarkConfiguration(
        periods_per_year=periods_per_year,
        block_size=block_size,
        n_bootstrap=n_bootstrap,
        random_seed=random_seed,
    )
    findings = [*_validate_identity(benchmark), *_validate_configuration(configuration)]

    strategy_returns, strategy_error = _prepare_daily_returns(
        strategy_series,
        strategy_series_kind,
        "strategy",
    )
    benchmark_returns, benchmark_error = _prepare_daily_returns(
        benchmark_series,
        benchmark_series_kind,
        "benchmark",
    )
    if strategy_error:
        findings.append(strategy_error)
    if benchmark_error:
        findings.append(benchmark_error)

    aligned = _align_returns(strategy_returns, benchmark_returns)
    alignment = _alignment_evidence(
        strategy_series,
        benchmark_series,
        strategy_returns,
        benchmark_returns,
        aligned,
    )
    if findings:
        return _blocked_analysis(
            benchmark,
            strategy_series_kind,
            benchmark_series_kind,
            configuration,
            alignment,
            findings,
        )

    required_observations = max(2, block_size)
    if len(aligned) < required_observations:
        return _blocked_analysis(
            benchmark,
            strategy_series_kind,
            benchmark_series_kind,
            configuration,
            alignment,
            [
                "Insufficient aligned return observations: "
                f"found {len(aligned)}, require at least {required_observations} for the "
                "configured tracking-error and moving-block bootstrap analysis."
            ],
        )

    point_metrics = _compute_metrics(aligned, periods_per_year)
    if point_metrics is None:
        return _blocked_analysis(
            benchmark,
            strategy_series_kind,
            benchmark_series_kind,
            configuration,
            alignment,
            ["The annualized point estimates are not finite for the supplied data."],
        )

    excess_ci, information_ratio_ci = _bootstrap_intervals(
        aligned,
        configuration,
    )
    watch_findings: list[str] = []
    if alignment.strategy_unmatched_observations or alignment.benchmark_unmatched_observations:
        watch_findings.append(
            "The input calendars differ; metrics use only dates present in both return series."
        )
    if not benchmark.total_return:
        watch_findings.append(
            "The benchmark is identified as price return rather than total return; dividends may "
            "limit comparability."
        )
    if point_metrics.information_ratio is None:
        watch_findings.append(
            "Information ratio is unavailable because aligned active returns have zero tracking "
            "error."
        )
    if excess_ci.status != "PASS":
        watch_findings.append(
            "The annualized excess-return interval used fewer than two valid bootstrap samples."
        )
    if information_ratio_ci.status != "PASS" and point_metrics.information_ratio is not None:
        watch_findings.append(
            "Some bootstrap samples had zero tracking error; the information-ratio interval uses "
            "only valid samples."
        )

    status: BenchmarkStatus = "WATCH" if watch_findings else "PASS"
    if not watch_findings:
        watch_findings.append("All requested benchmark statistics and intervals are available.")
    return BenchmarkAnalysis(
        status=status,
        benchmark=benchmark,
        strategy_series_kind=strategy_series_kind,
        benchmark_series_kind=benchmark_series_kind,
        configuration=configuration,
        alignment=alignment,
        metrics=point_metrics,
        annualized_excess_return_ci=excess_ci,
        information_ratio_ci=information_ratio_ci,
        findings=watch_findings,
    )


def _validate_identity(benchmark: BenchmarkIdentity) -> list[str]:
    findings = []
    if not isinstance(benchmark.symbol, str) or not benchmark.symbol.strip():
        findings.append("Benchmark symbol must be a non-empty string.")
    if not isinstance(benchmark.name, str) or not benchmark.name.strip():
        findings.append("Benchmark name must be a non-empty string.")
    if not isinstance(benchmark.total_return, bool):
        findings.append("Benchmark total_return must be a boolean.")
    return findings


def _validate_configuration(configuration: BenchmarkConfiguration) -> list[str]:
    findings = []
    for field_name in ("periods_per_year", "block_size", "n_bootstrap"):
        value = getattr(configuration, field_name)
        if not _is_positive_integer(value):
            findings.append(f"{field_name} must be a positive integer.")
    if _is_positive_integer(configuration.n_bootstrap) and configuration.n_bootstrap < 2:
        findings.append("n_bootstrap must be at least 2 to form a confidence interval.")
    if not _is_non_negative_integer(configuration.random_seed):
        findings.append("random_seed must be a non-negative integer.")
    return findings


def _prepare_daily_returns(
    series: pd.Series,
    kind: SeriesKind,
    label: str,
) -> tuple[pd.Series | None, str | None]:
    if kind not in {"equity", "returns"}:
        return None, f"{label}_series_kind must be 'equity' or 'returns'."
    if not isinstance(series, pd.Series):
        return None, f"{label} input must be a pandas Series."
    if series.empty:
        return None, f"{label} input is empty."
    if not isinstance(series.index, pd.DatetimeIndex) and pd.api.types.is_numeric_dtype(
        series.index.dtype
    ):
        return None, f"{label} input must use a date-like index, not a numeric index."

    try:
        dates = pd.DatetimeIndex(pd.to_datetime(series.index, errors="coerce"))
    except (TypeError, ValueError, OverflowError):
        return None, f"{label} input index cannot be converted to dates."
    if dates.isna().any():
        return None, f"{label} input contains an invalid date."
    if dates.tz is not None:
        dates = dates.tz_localize(None)
    dates = dates.normalize()
    if dates.duplicated().any():
        return None, f"{label} input contains duplicate calendar dates."

    if any(isinstance(value, (bool, np.bool_)) for value in series.array):
        return None, f"{label} input contains boolean rather than numeric values."
    try:
        values = series.to_numpy(dtype=float, na_value=np.nan)
    except (TypeError, ValueError):
        return None, f"{label} input contains non-numeric values."
    if not np.isfinite(values).all():
        return None, f"{label} input contains missing or non-finite values."

    prepared = pd.Series(values, index=dates, dtype=float).sort_index()
    if kind == "equity":
        if len(prepared) < 2:
            return None, f"{label} equity input requires at least two observations."
        if (prepared <= 0.0).any():
            return None, f"{label} equity values must be positive."
        returns = prepared.pct_change(fill_method=None).iloc[1:]
    else:
        if (prepared < -1.0).any():
            return None, f"{label} returns cannot be less than -1.0."
        returns = prepared
    return returns.astype(float), None


def _align_returns(
    strategy_returns: pd.Series | None,
    benchmark_returns: pd.Series | None,
) -> pd.DataFrame:
    if strategy_returns is None or benchmark_returns is None:
        return pd.DataFrame(columns=["strategy", "benchmark"], dtype=float)
    return pd.concat(
        [
            strategy_returns.rename("strategy"),
            benchmark_returns.rename("benchmark"),
        ],
        axis=1,
        join="inner",
    ).sort_index()


def _alignment_evidence(
    strategy_input: object,
    benchmark_input: object,
    strategy_returns: pd.Series | None,
    benchmark_returns: pd.Series | None,
    aligned: pd.DataFrame,
) -> AlignmentEvidence:
    strategy_return_count = len(strategy_returns) if strategy_returns is not None else 0
    benchmark_return_count = len(benchmark_returns) if benchmark_returns is not None else 0
    start_date = aligned.index[0].date().isoformat() if not aligned.empty else None
    end_date = aligned.index[-1].date().isoformat() if not aligned.empty else None
    return AlignmentEvidence(
        strategy_input_observations=_safe_len(strategy_input),
        benchmark_input_observations=_safe_len(benchmark_input),
        strategy_return_observations=strategy_return_count,
        benchmark_return_observations=benchmark_return_count,
        aligned_observations=len(aligned),
        strategy_unmatched_observations=max(0, strategy_return_count - len(aligned)),
        benchmark_unmatched_observations=max(0, benchmark_return_count - len(aligned)),
        start_date=start_date,
        end_date=end_date,
    )


def _compute_metrics(aligned: pd.DataFrame, periods_per_year: int) -> BenchmarkMetrics | None:
    strategy = aligned["strategy"].to_numpy(dtype=float)
    benchmark = aligned["benchmark"].to_numpy(dtype=float)
    strategy_cagr = _cagr(strategy, periods_per_year)
    benchmark_cagr = _cagr(benchmark, periods_per_year)
    if strategy_cagr is None or benchmark_cagr is None:
        return None

    active = strategy - benchmark
    annualized_excess_return = float(active.mean() * periods_per_year)
    daily_tracking_error = float(active.std(ddof=1))
    if not np.isfinite(annualized_excess_return) or not np.isfinite(daily_tracking_error):
        return None
    if _effectively_zero(daily_tracking_error, active):
        annualized_tracking_error = 0.0
        information_ratio = None
    else:
        annualized_tracking_error = float(daily_tracking_error * sqrt(periods_per_year))
        information_ratio = float(annualized_excess_return / annualized_tracking_error)
        if not np.isfinite(annualized_tracking_error) or not np.isfinite(information_ratio):
            return None
    return BenchmarkMetrics(
        strategy_cagr=strategy_cagr,
        benchmark_cagr=benchmark_cagr,
        excess_cagr=float(strategy_cagr - benchmark_cagr),
        annualized_excess_return=annualized_excess_return,
        annualized_tracking_error=annualized_tracking_error,
        information_ratio=information_ratio,
    )


def _cagr(returns: np.ndarray, periods_per_year: int) -> float | None:
    if np.any(returns == -1.0):
        return -1.0
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        annualized_log_return = np.log1p(returns).sum() * periods_per_year / len(returns)
        value = np.expm1(annualized_log_return)
    return float(value) if np.isfinite(value) else None


def _bootstrap_intervals(
    aligned: pd.DataFrame,
    configuration: BenchmarkConfiguration,
) -> tuple[BootstrapConfidenceInterval, BootstrapConfidenceInterval]:
    active = (
        aligned["strategy"].to_numpy(dtype=float)
        - aligned["benchmark"].to_numpy(dtype=float)
    )
    rng = np.random.default_rng(configuration.random_seed)
    blocks_needed = ceil(len(active) / configuration.block_size)
    maximum_start = len(active) - configuration.block_size
    block_offsets = np.arange(configuration.block_size)
    annualized_excess_samples: list[float] = []
    information_ratio_samples: list[float] = []

    for _ in range(configuration.n_bootstrap):
        starts = rng.integers(0, maximum_start + 1, size=blocks_needed)
        sample_indices = (starts[:, None] + block_offsets).reshape(-1)[: len(active)]
        sample = active[sample_indices]
        annualized_excess = float(sample.mean() * configuration.periods_per_year)
        if np.isfinite(annualized_excess):
            annualized_excess_samples.append(annualized_excess)
        daily_tracking_error = float(sample.std(ddof=1))
        if _effectively_zero(daily_tracking_error, sample):
            continue
        tracking_error = daily_tracking_error * sqrt(configuration.periods_per_year)
        information_ratio = annualized_excess / tracking_error
        if np.isfinite(information_ratio):
            information_ratio_samples.append(float(information_ratio))

    return (
        _confidence_interval(annualized_excess_samples, configuration.n_bootstrap),
        _confidence_interval(information_ratio_samples, configuration.n_bootstrap),
    )


def _confidence_interval(
    samples: list[float],
    samples_requested: int,
) -> BootstrapConfidenceInterval:
    samples_used = len(samples)
    if samples_used < 2:
        return BootstrapConfidenceInterval(
            status="BLOCK",
            lower=None,
            upper=None,
            confidence_level=0.95,
            method="moving_block_bootstrap_percentile",
            samples_requested=samples_requested,
            samples_used=samples_used,
        )
    lower, upper = np.quantile(np.asarray(samples, dtype=float), [0.025, 0.975])
    status: BenchmarkStatus = "PASS" if samples_used == samples_requested else "WATCH"
    return BootstrapConfidenceInterval(
        status=status,
        lower=float(lower),
        upper=float(upper),
        confidence_level=0.95,
        method="moving_block_bootstrap_percentile",
        samples_requested=samples_requested,
        samples_used=samples_used,
    )


def _blocked_analysis(
    benchmark: BenchmarkIdentity,
    strategy_series_kind: SeriesKind,
    benchmark_series_kind: SeriesKind,
    configuration: BenchmarkConfiguration,
    alignment: AlignmentEvidence,
    findings: list[str],
) -> BenchmarkAnalysis:
    unavailable_interval = BootstrapConfidenceInterval(
        status="BLOCK",
        lower=None,
        upper=None,
        confidence_level=0.95,
        method="moving_block_bootstrap_percentile",
        samples_requested=(
            configuration.n_bootstrap if _is_positive_integer(configuration.n_bootstrap) else 0
        ),
        samples_used=0,
    )
    return BenchmarkAnalysis(
        status="BLOCK",
        benchmark=benchmark,
        strategy_series_kind=strategy_series_kind,
        benchmark_series_kind=benchmark_series_kind,
        configuration=configuration,
        alignment=alignment,
        metrics=BenchmarkMetrics(
            strategy_cagr=None,
            benchmark_cagr=None,
            excess_cagr=None,
            annualized_excess_return=None,
            annualized_tracking_error=None,
            information_ratio=None,
        ),
        annualized_excess_return_ci=unavailable_interval,
        information_ratio_ci=unavailable_interval,
        findings=findings,
    )


def _effectively_zero(value: float, observations: np.ndarray) -> bool:
    scale = max(1.0, float(np.max(np.abs(observations), initial=0.0)))
    return abs(value) <= np.finfo(float).eps * scale * 16.0


def _is_positive_integer(value: object) -> bool:
    return isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_)) and value > 0


def _is_non_negative_integer(value: object) -> bool:
    return isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_)) and value >= 0


def _safe_len(value: object) -> int:
    try:
        return len(value)  # type: ignore[arg-type]
    except TypeError:
        return 0
