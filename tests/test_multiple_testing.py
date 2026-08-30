from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantify.research.multiple_testing import (
    cscv_probability_of_backtest_overfitting,
    deflated_sharpe_ratio,
)


def test_deflated_sharpe_distinguishes_strong_and_weak_results() -> None:
    strong = deflated_sharpe_ratio(
        observed_annualized_sharpe=2.0,
        effective_trials=10,
        observations=756,
        periods_per_year=252,
        skewness=0.0,
        excess_kurtosis=0.0,
    )
    weak = deflated_sharpe_ratio(
        observed_annualized_sharpe=0.5,
        effective_trials=100,
        observations=756,
        periods_per_year=252,
        skewness=0.0,
        excess_kurtosis=0.0,
    )

    assert strong.status == "PASS"
    assert strong.sufficient is True
    assert strong.expected_maximum_sharpe is not None
    assert strong.standard_error is not None
    assert strong.dsr_probability is not None and strong.dsr_probability > 0.95
    assert weak.status == "BLOCK"
    assert weak.dsr_probability is not None and weak.dsr_probability < 0.20
    assert weak.expected_maximum_sharpe is not None
    assert strong.expected_maximum_sharpe < weak.expected_maximum_sharpe
    assert strong.to_dict()["evidence"][1]["code"] == "DSR_PROBABILITY_PASS"


def test_deflated_sharpe_fails_closed_for_small_or_incoherent_samples() -> None:
    small = deflated_sharpe_ratio(
        observed_annualized_sharpe=3.0,
        effective_trials=5,
        observations=12,
        periods_per_year=252,
        skewness=0.0,
        excess_kurtosis=0.0,
    )
    incoherent = deflated_sharpe_ratio(
        observed_annualized_sharpe=20.0,
        effective_trials=5,
        observations=252,
        periods_per_year=252,
        skewness=10.0,
        excess_kurtosis=-2.0,
    )

    assert small.status == "BLOCK"
    assert small.sufficient is False
    assert small.dsr_probability is None
    assert small.standard_error is None
    assert "below minimum_observations" in small.insufficiency_reasons[0]
    assert incoherent.sufficient is False
    assert incoherent.expected_maximum_sharpe is None
    assert "non-positive" in incoherent.insufficiency_reasons[0]


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"effective_trials": 0.5}, "effective_trials"),
        ({"periods_per_year": 0}, "periods_per_year"),
        ({"observations": 20.5}, "observations"),
        ({"excess_kurtosis": -2.1}, "excess_kurtosis"),
        ({"pass_probability": 0.7, "watch_probability": 0.8}, "thresholds"),
    ],
)
def test_deflated_sharpe_rejects_invalid_inputs(
    override: dict[str, float],
    message: str,
) -> None:
    arguments: dict[str, float | int] = {
        "observed_annualized_sharpe": 1.0,
        "effective_trials": 5,
        "observations": 252,
        "periods_per_year": 252,
        "skewness": 0.0,
        "excess_kurtosis": 0.0,
    }
    arguments.update(override)

    with pytest.raises((TypeError, ValueError), match=message):
        deflated_sharpe_ratio(**arguments)


def test_cscv_stable_matrix_has_no_selection_overfitting() -> None:
    frame = _stable_returns_frame()

    result = cscv_probability_of_backtest_overfitting(frame, partition_count=8)

    assert result.status == "PASS"
    assert result.sufficient is True
    assert result.total_combinations == 70
    assert result.evaluated_combinations == 70
    assert result.pbo == 0.0
    assert result.degradation_probability == 0.0
    assert {split.in_sample_winner for split in result.splits} == {"stable_best"}
    assert result.to_dict()["splits"][0]["in_sample_partitions"] == [0, 1, 2, 3]


def test_cscv_capped_combinations_are_reproducible_and_spread() -> None:
    frame = _overfit_returns_frame()

    first = cscv_probability_of_backtest_overfitting(
        frame,
        partition_count=8,
        max_combinations=11,
    )
    second = cscv_probability_of_backtest_overfitting(
        frame.sample(frac=1.0, random_state=91),
        partition_count=8,
        max_combinations=11,
    )

    assert first == second
    assert first.evaluated_combinations == 11
    assert first.total_combinations == 70
    assert first.splits[0].in_sample_partitions == (0, 1, 2, 3)
    assert first.splits[-1].in_sample_partitions == (4, 5, 6, 7)
    assert first.evidence[-1].code == "CSCV_COMBINATIONS_CAPPED"
    assert first.status == "BLOCK"


def test_cscv_detects_partition_specific_overfit_matrix() -> None:
    result = cscv_probability_of_backtest_overfitting(
        _overfit_returns_frame(),
        partition_count=8,
    )

    assert result.pbo == 1.0
    assert result.degradation_probability == 1.0
    assert result.status == "BLOCK"
    assert all(logit < 0.0 for logit in result.rank_logits)
    assert all(split.degraded for split in result.splits)


def test_cscv_fails_closed_when_partitions_are_too_small() -> None:
    frame = pd.DataFrame(
        {"one": np.arange(7, dtype=float), "two": np.arange(7, dtype=float) / 2.0},
        index=pd.date_range("2025-01-01", periods=7, freq="D"),
    )

    result = cscv_probability_of_backtest_overfitting(frame, partition_count=4)

    assert result.status == "BLOCK"
    assert result.sufficient is False
    assert result.pbo is None
    assert result.degradation_probability is None
    assert result.evaluated_combinations == 0
    assert "partition sizes" in result.insufficiency_reasons[0]


def test_cscv_fails_closed_when_half_sample_sharpe_is_undefined() -> None:
    dates = pd.date_range("2025-01-01", periods=32, freq="D")
    frame = pd.DataFrame(
        {
            "constant": np.full(32, 0.001),
            "varying": np.tile(np.array([-0.002, 0.003]), 16),
        },
        index=dates,
    )

    result = cscv_probability_of_backtest_overfitting(frame, partition_count=4)

    assert result.status == "BLOCK"
    assert result.sufficient is False
    assert result.pbo is None
    assert result.splits == ()
    assert "zero return variance" in result.insufficiency_reasons[0]


def test_cscv_rejects_one_trial_and_invalid_frames() -> None:
    dates = pd.date_range("2025-01-01", periods=16, freq="D")
    one_trial = pd.DataFrame({"only": np.linspace(-0.01, 0.01, 16)}, index=dates)
    missing = pd.DataFrame(
        {"one": np.linspace(-0.01, 0.01, 16), "two": np.linspace(0.01, -0.01, 16)},
        index=dates,
    )
    missing.iloc[3, 0] = np.nan

    with pytest.raises(ValueError, match="at least two trials"):
        cscv_probability_of_backtest_overfitting(one_trial, partition_count=4)
    with pytest.raises(ValueError, match="finite values"):
        cscv_probability_of_backtest_overfitting(missing, partition_count=4)
    with pytest.raises(ValueError, match="DatetimeIndex"):
        cscv_probability_of_backtest_overfitting(missing.reset_index(drop=True), partition_count=4)
    with pytest.raises(ValueError, match="even integer"):
        cscv_probability_of_backtest_overfitting(_stable_returns_frame(), partition_count=5)


def _stable_returns_frame() -> pd.DataFrame:
    partition_pattern = np.array([-0.0015, -0.0010, -0.0005, 0.0, 0.0005, 0.0010, 0.0015, 0.0020])
    repeated_pattern = np.tile(partition_pattern, 8)
    return pd.DataFrame(
        {
            "stable_best": 0.0040 + repeated_pattern,
            "stable_middle": 0.0015 + repeated_pattern * 1.4,
            "stable_weak": -0.0010 + repeated_pattern * 1.8,
        },
        index=pd.date_range("2024-01-01", periods=len(repeated_pattern), freq="D"),
    )


def _overfit_returns_frame() -> pd.DataFrame:
    partition_count = 8
    rows_per_partition = 12
    within_partition = np.linspace(-0.001, 0.001, rows_per_partition)
    values = np.empty((partition_count * rows_per_partition, partition_count), dtype=float)
    for partition in range(partition_count):
        row_slice = slice(partition * rows_per_partition, (partition + 1) * rows_per_partition)
        for trial in range(partition_count):
            regime_mean = 0.04 if trial == partition else -0.004
            values[row_slice, trial] = regime_mean + within_partition * (1.0 + trial / 20.0)
    return pd.DataFrame(
        values,
        columns=[f"trial_{index}" for index in range(partition_count)],
        index=pd.date_range("2024-01-01", periods=len(values), freq="D"),
    )
