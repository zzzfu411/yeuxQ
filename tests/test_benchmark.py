from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantify.research.benchmark import BenchmarkIdentity, analyze_benchmark


BENCHMARK = BenchmarkIdentity(
    symbol="000300.SH",
    name="CSI 300 Total Return",
    total_return=True,
)


def test_return_series_align_on_common_dates() -> None:
    strategy = pd.Series(
        [0.01, 0.02, -0.01, 0.03, 0.00, 0.015],
        index=pd.date_range("2024-01-01", periods=6),
    )
    benchmark = pd.Series(
        [0.005, 0.01, -0.005, 0.015, 0.002, 0.007],
        index=pd.date_range("2024-01-02", periods=6),
    )

    report = analyze_benchmark(
        strategy,
        benchmark,
        BENCHMARK,
        strategy_series_kind="returns",
        benchmark_series_kind="returns",
        periods_per_year=5,
        block_size=2,
        n_bootstrap=200,
        random_seed=11,
    )

    aligned_strategy = strategy.loc["2024-01-02":"2024-01-06"].to_numpy()
    aligned_benchmark = benchmark.loc["2024-01-02":"2024-01-06"].to_numpy()
    active = aligned_strategy - aligned_benchmark
    expected_strategy_cagr = np.prod(1.0 + aligned_strategy) - 1.0
    expected_benchmark_cagr = np.prod(1.0 + aligned_benchmark) - 1.0

    assert report.status == "WATCH"
    assert report.alignment.aligned_observations == 5
    assert report.alignment.strategy_unmatched_observations == 1
    assert report.alignment.benchmark_unmatched_observations == 1
    assert report.alignment.start_date == "2024-01-02"
    assert report.alignment.end_date == "2024-01-06"
    assert report.metrics.strategy_cagr == pytest.approx(expected_strategy_cagr)
    assert report.metrics.benchmark_cagr == pytest.approx(expected_benchmark_cagr)
    assert report.metrics.excess_cagr == pytest.approx(
        expected_strategy_cagr - expected_benchmark_cagr
    )
    assert report.metrics.annualized_excess_return == pytest.approx(active.mean() * 5)
    assert report.metrics.annualized_tracking_error == pytest.approx(active.std(ddof=1) * np.sqrt(5))
    assert report.metrics.information_ratio == pytest.approx(
        active.mean() / active.std(ddof=1) * np.sqrt(5)
    )
    assert report.to_dict()["benchmark"] == {
        "symbol": "000300.SH",
        "name": "CSI 300 Total Return",
        "total_return": True,
    }


def test_equity_series_are_converted_to_returns_before_analysis() -> None:
    dates = pd.date_range("2024-02-01", periods=5)
    strategy = pd.Series([100.0, 110.0, 110.0, 121.0, 121.0], index=dates)
    benchmark = pd.Series([100.0, 105.0, 105.0, 110.25, 110.25], index=dates)

    report = analyze_benchmark(
        strategy,
        benchmark,
        BENCHMARK,
        periods_per_year=4,
        block_size=4,
        n_bootstrap=50,
        random_seed=3,
    )

    assert report.status == "PASS"
    assert report.alignment.aligned_observations == 4
    assert report.metrics.strategy_cagr == pytest.approx(0.21)
    assert report.metrics.benchmark_cagr == pytest.approx(0.1025)
    assert report.metrics.excess_cagr == pytest.approx(0.1075)
    assert report.annualized_excess_return_ci.status == "PASS"
    assert report.information_ratio_ci.status == "PASS"


def test_zero_tracking_error_does_not_fabricate_information_ratio() -> None:
    dates = pd.date_range("2024-03-01", periods=8)
    returns = pd.Series([0.01, -0.005, 0.012, 0.0, 0.006, -0.002, 0.004, 0.009], index=dates)

    report = analyze_benchmark(
        returns,
        returns.copy(),
        BENCHMARK,
        strategy_series_kind="returns",
        benchmark_series_kind="returns",
        block_size=3,
        n_bootstrap=100,
        random_seed=7,
    )

    assert report.status == "WATCH"
    assert report.metrics.annualized_tracking_error == 0.0
    assert report.metrics.information_ratio is None
    assert report.information_ratio_ci.status == "BLOCK"
    assert report.information_ratio_ci.lower is None
    assert report.information_ratio_ci.upper is None
    assert report.annualized_excess_return_ci.lower == pytest.approx(0.0)
    assert report.annualized_excess_return_ci.upper == pytest.approx(0.0)


def test_moving_block_bootstrap_is_reproducible() -> None:
    dates = pd.date_range("2024-04-01", periods=20)
    strategy = pd.Series(
        [
            0.012,
            -0.008,
            0.006,
            0.015,
            -0.004,
            0.003,
            0.009,
            -0.011,
            0.007,
            0.002,
            0.013,
            -0.006,
            0.004,
            0.010,
            -0.003,
            0.005,
            0.008,
            -0.007,
            0.011,
            0.001,
        ],
        index=dates,
    )
    benchmark = pd.Series(
        [
            0.007,
            -0.005,
            0.004,
            0.009,
            -0.002,
            0.001,
            0.006,
            -0.008,
            0.003,
            0.001,
            0.008,
            -0.004,
            0.002,
            0.007,
            -0.001,
            0.003,
            0.005,
            -0.004,
            0.006,
            0.0,
        ],
        index=dates,
    )
    kwargs = {
        "strategy_series_kind": "returns",
        "benchmark_series_kind": "returns",
        "block_size": 4,
        "n_bootstrap": 300,
        "random_seed": 12345,
    }

    first = analyze_benchmark(strategy, benchmark, BENCHMARK, **kwargs)
    second = analyze_benchmark(strategy, benchmark, BENCHMARK, **kwargs)

    assert first.annualized_excess_return_ci == second.annualized_excess_return_ci
    assert first.information_ratio_ci == second.information_ratio_ci
    assert first.to_dict() == second.to_dict()


def test_insufficient_aligned_observations_return_block_evidence() -> None:
    dates = pd.date_range("2024-05-01", periods=3)
    strategy = pd.Series([0.01, 0.02, -0.01], index=dates)
    benchmark = pd.Series([0.005, 0.01, -0.005], index=dates)

    report = analyze_benchmark(
        strategy,
        benchmark,
        BENCHMARK,
        strategy_series_kind="returns",
        benchmark_series_kind="returns",
        block_size=4,
        n_bootstrap=50,
    )

    assert report.status == "BLOCK"
    assert report.alignment.aligned_observations == 3
    assert all(value is None for value in report.metrics.to_dict().values())
    assert report.annualized_excess_return_ci.samples_used == 0
    assert report.information_ratio_ci.samples_used == 0
    assert "require at least 4" in report.findings[0]


def test_invalid_values_return_block_evidence() -> None:
    dates = pd.date_range("2024-06-01", periods=6)
    strategy = pd.Series([0.01, 0.02, np.nan, 0.0, 0.005, -0.002], index=dates)
    benchmark = pd.Series([0.005, 0.01, 0.0, 0.003, 0.002, -0.001], index=dates)

    report = analyze_benchmark(
        strategy,
        benchmark,
        BENCHMARK,
        strategy_series_kind="returns",
        benchmark_series_kind="returns",
        block_size=2,
        n_bootstrap=50,
    )

    assert report.status == "BLOCK"
    assert report.metrics.strategy_cagr is None
    assert any("missing or non-finite" in finding for finding in report.findings)
