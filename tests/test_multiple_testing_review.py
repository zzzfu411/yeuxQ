from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from quantify.research.multiple_testing import (
    build_multiple_testing_report,
    write_multiple_testing_report,
)


def test_multiple_testing_report_records_provenance_statistics_and_diagnostics(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "frozen_trials.csv"
    _stable_returns_frame().to_csv(csv_path, index_label="date")

    report = build_multiple_testing_report(
        csv_path,
        selected_candidate="stable_best",
        periods_per_year=252,
        partition_count=8,
    )
    output = write_multiple_testing_report(report, tmp_path / "review")
    payload = json.loads((output / "multiple_testing_report.json").read_text(encoding="utf-8"))

    assert report.status == "PASS"
    assert report.sufficient is True
    assert report.input_sha256 == hashlib.sha256(csv_path.read_bytes()).hexdigest()
    assert report.candidate_columns == ("stable_best", "stable_middle", "stable_weak")
    assert report.observation_start == "2024-01-01"
    assert report.observation_end == "2024-03-04"
    assert report.effective_trials == 3.0
    assert report.effective_trials_source == "trial_column_count"
    assert report.selected_annualized_sharpe is not None
    assert report.selected_skewness is not None
    assert report.selected_excess_kurtosis is not None
    assert report.dsr is not None and report.dsr.status == "PASS"
    assert report.cscv_pbo is not None and report.cscv_pbo.pbo == 0.0
    assert payload["artifact_type"] == "multiple_testing_report"
    assert payload["evidence_role"] == "diagnostic_only"
    assert payload["can_upgrade_deterministic_gate"] is False
    assert payload["input"]["sha256"] == report.input_sha256
    assert payload["parameters"]["partition_count"] == 8
    assert payload["insufficiency_reasons"] == []
    assert "cannot by itself upgrade" in (output / "multiple_testing_report.md").read_text(
        encoding="utf-8"
    )


def test_multiple_testing_report_accepts_only_conservative_effective_trial_override(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "frozen_trials.csv"
    _stable_returns_frame().to_csv(csv_path, index_label="date")

    conservative = build_multiple_testing_report(
        csv_path,
        selected_candidate="stable_best",
        periods_per_year=252,
        partition_count=8,
        effective_trials=7,
    )
    optimistic = build_multiple_testing_report(
        csv_path,
        selected_candidate="stable_best",
        periods_per_year=252,
        partition_count=8,
        effective_trials=2,
    )

    assert conservative.effective_trials == 7.0
    assert conservative.effective_trials_source == "explicit_conservative_override"
    assert conservative.dsr is not None and conservative.dsr.effective_trials == 7.0
    assert optimistic.status == "BLOCK"
    assert optimistic.sufficient is False
    assert optimistic.dsr is None
    assert optimistic.cscv_pbo is None
    assert "cannot be below trial_count=3" in optimistic.insufficiency_reasons[0]


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ("small", "below the report minimum"),
        ("single", "At least two frozen trial columns"),
        ("nonfinite", "non-finite values"),
    ],
)
def test_multiple_testing_report_fails_closed_without_pseudo_precision(
    tmp_path: Path,
    case: str,
    expected_reason: str,
) -> None:
    csv_path = tmp_path / f"{case}.csv"
    frame = _stable_returns_frame()
    if case == "small":
        frame = frame.iloc[:12]
    elif case == "single":
        frame = frame[["stable_best"]]
    else:
        frame.iloc[5, 1] = np.inf
    frame.to_csv(csv_path, index_label="date")

    report = build_multiple_testing_report(
        csv_path,
        selected_candidate="stable_best",
        periods_per_year=252,
        partition_count=8,
    )
    payload = report.to_dict()

    assert report.status == "BLOCK"
    assert report.sufficient is False
    assert report.input_sha256 == hashlib.sha256(csv_path.read_bytes()).hexdigest()
    assert report.dsr is None
    assert report.cscv_pbo is None
    assert report.selected_annualized_sharpe is None
    assert payload["selected_statistics"] == {
        "annualized_sharpe": None,
        "sample_skewness": None,
        "sample_excess_kurtosis": None,
    }
    assert any(expected_reason in reason for reason in report.insufficiency_reasons)


def test_multiple_testing_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    csv_path = tmp_path / "frozen_trials.csv"
    output = tmp_path / "review"
    _stable_returns_frame().to_csv(csv_path, index_label="date")

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_multiple_testing_review.py",
            "--input-csv",
            str(csv_path),
            "--output-dir",
            str(output),
            "--selected-candidate",
            "stable_best",
            "--periods-per-year",
            "252",
            "--partition-count",
            "8",
            "--max-combinations",
            "11",
            "--effective-trials",
            "5",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Multiple-testing status:" in completed.stdout
    assert (output / "multiple_testing_report.json").exists()
    assert (output / "multiple_testing_report.md").exists()
    payload = json.loads((output / "multiple_testing_report.json").read_text(encoding="utf-8"))
    assert payload["status"] == "WATCH"
    assert payload["parameters"]["max_combinations"] == 11
    assert payload["parameters"]["effective_trials"] == 5.0
    assert payload["diagnostics"]["cscv_pbo"]["evaluated_combinations"] == 11


def test_multiple_testing_cli_writes_block_report_for_single_trial(tmp_path: Path) -> None:
    csv_path = tmp_path / "one_trial.csv"
    output = tmp_path / "blocked_review"
    _stable_returns_frame()[["stable_best"]].to_csv(csv_path, index_label="date")

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_multiple_testing_review.py",
            "--input-csv",
            str(csv_path),
            "--output-dir",
            str(output),
            "--selected-candidate",
            "stable_best",
            "--periods-per-year",
            "252",
            "--partition-count",
            "8",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads((output / "multiple_testing_report.json").read_text(encoding="utf-8"))

    assert completed.returncode == 0, completed.stderr
    assert payload["status"] == "BLOCK"
    assert payload["diagnostics"] == {
        "deflated_sharpe_ratio": None,
        "cscv_pbo": None,
    }
    assert any(
        "At least two frozen trial columns" in reason for reason in payload["insufficiency_reasons"]
    )
    assert (output / "multiple_testing_report.md").exists()


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
