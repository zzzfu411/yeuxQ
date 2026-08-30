from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from tests.statistical_evidence_fixtures import write_statistical_evidence_fixtures

from quantify.research.benchmark_report import build_benchmark_review_report
from quantify.research.evidence_validation import (
    validate_benchmark_payload,
    validate_multiple_testing_payload,
    validate_trial_registry_review_payload,
)
from quantify.research.multiple_testing import build_multiple_testing_report


def test_complete_multiple_testing_report_validates(tmp_path: Path) -> None:
    input_csv = tmp_path / "returns.csv"
    _returns_frame().to_csv(input_csv, index_label="date")
    report = build_multiple_testing_report(
        input_csv,
        selected_candidate="stable_best",
        periods_per_year=252,
        partition_count=8,
    )

    validation = validate_multiple_testing_payload(
        report.to_dict(),
        expected_candidate="stable_best",
    )

    assert validation.valid is True
    assert validation.status == report.status


def test_bare_or_candidate_mismatched_payload_fails_closed(tmp_path: Path) -> None:
    bare = validate_multiple_testing_payload(
        {"status": "PASS"},
        expected_candidate="stable_best",
        verify_input_file=False,
    )

    assert bare.valid is False
    assert any("artifact_type" in reason for reason in bare.reasons)

    input_csv = tmp_path / "returns.csv"
    _returns_frame().to_csv(input_csv, index_label="date")
    payload = build_multiple_testing_report(
        input_csv,
        selected_candidate="stable_best",
        periods_per_year=252,
        partition_count=8,
    ).to_dict()
    mismatch = validate_multiple_testing_payload(payload, expected_candidate="other")
    assert mismatch.valid is False
    assert any("deterministic selected candidate" in reason for reason in mismatch.reasons)


def test_tampered_input_or_diagnostic_status_fails_closed(tmp_path: Path) -> None:
    input_csv = tmp_path / "returns.csv"
    _returns_frame().to_csv(input_csv, index_label="date")
    payload = build_multiple_testing_report(
        input_csv,
        selected_candidate="stable_best",
        periods_per_year=252,
        partition_count=8,
    ).to_dict()

    input_csv.write_text(input_csv.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    tampered_input = validate_multiple_testing_payload(payload)
    assert tampered_input.valid is False
    assert any("SHA-256" in reason for reason in tampered_input.reasons)

    payload = deepcopy(payload)
    payload["input"]["csv_path"] = "ignored.csv"
    payload["diagnostics"]["deflated_sharpe_ratio"]["status"] = "PASS"
    payload["diagnostics"]["cscv_pbo"]["status"] = "PASS"
    payload["status"] = "BLOCK"
    inconsistent = validate_multiple_testing_payload(payload, verify_input_file=False)
    assert inconsistent.valid is False
    assert any("worst DSR" in reason for reason in inconsistent.reasons)


def test_formal_benchmark_contract_validates_expected_index(tmp_path: Path) -> None:
    report, _strategy_path = _benchmark_report(tmp_path)

    validation = validate_benchmark_payload(
        report.to_dict(),
        expected_symbol="000906",
    )

    assert report.status == "PASS"
    assert validation.valid is True


def test_benchmark_identity_or_retained_input_change_fails_closed(tmp_path: Path) -> None:
    report, strategy_path = _benchmark_report(tmp_path)
    wrong_index = validate_benchmark_payload(
        report.to_dict(),
        expected_symbol="000300",
    )
    assert wrong_index.valid is False
    assert any("index_code" in reason for reason in wrong_index.reasons)

    strategy_path.write_text(
        strategy_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    changed = validate_benchmark_payload(report.to_dict(), expected_symbol="000906")
    assert changed.valid is False
    assert any("strategy_equity_csv" in reason for reason in changed.reasons)


def test_shared_statistical_evidence_fixture_satisfies_all_contracts(tmp_path: Path) -> None:
    write_statistical_evidence_fixtures(tmp_path, candidate="core_multifactor")
    multiple = json.loads((tmp_path / "multiple_testing_report.json").read_text(encoding="utf-8"))
    benchmark = json.loads((tmp_path / "benchmark_report.json").read_text(encoding="utf-8"))
    trial = json.loads((tmp_path / "trial_registry_review.json").read_text(encoding="utf-8"))

    assert validate_multiple_testing_payload(
        multiple,
        expected_candidate="core_multifactor",
    ).valid
    assert validate_benchmark_payload(benchmark, expected_symbol="000906").valid
    assert validate_trial_registry_review_payload(
        trial,
        expected_candidate="core_multifactor",
        report_dir=tmp_path,
    ).valid


def _returns_frame() -> pd.DataFrame:
    pattern = np.array([-0.0015, -0.0010, -0.0005, 0.0, 0.0005, 0.0010, 0.0015, 0.0020])
    repeated = np.tile(pattern, 8)
    return pd.DataFrame(
        {
            "stable_best": 0.0040 + repeated,
            "stable_middle": 0.0015 + repeated * 1.4,
            "stable_weak": -0.0010 + repeated * 1.8,
        },
        index=pd.date_range("2024-01-01", periods=len(repeated), freq="D"),
    )


def _benchmark_report(tmp_path: Path):
    active_returns = np.tile(np.array([0.0010, 0.0018, 0.0026, 0.0014, 0.0022]), 8)
    benchmark_returns = np.tile(
        np.array([0.0010, -0.0008, 0.0015, 0.0002, -0.0004]),
        8,
    )
    strategy_returns = benchmark_returns + active_returns
    dates = pd.date_range("2024-01-01", periods=len(active_returns) + 1, freq="D")
    strategy_equity = 100_000.0 * np.cumprod(
        np.concatenate(([1.0], 1.0 + strategy_returns))
    )
    strategy_path = tmp_path / "strategy.csv"
    benchmark_path = tmp_path / "benchmark.csv"
    metadata_path = tmp_path / "benchmark_metadata.json"
    pd.DataFrame({"timestamp": dates, "equity": strategy_equity}).to_csv(
        strategy_path,
        index=False,
    )
    pd.DataFrame({"date": dates[1:], "value": benchmark_returns}).to_csv(
        benchmark_path,
        index=False,
    )
    benchmark_sha = hashlib.sha256(benchmark_path.read_bytes()).hexdigest()
    metadata_path.write_text(
        json.dumps(
            {
                "artifact_type": "reviewed_benchmark_series",
                "schema_version": 1,
                "symbol": "000906.SH",
                "name": "CSI 800 Total Return",
                "total_return": True,
                "series_kind": "returns",
                "source_vendor": "licensed-test-vendor",
                "source_exported_at": "2026-07-15T09:30:00+08:00",
                "reviewed_by": "research-operator",
                "reviewed_at": "2026-07-15T10:00:00+08:00",
                "file_sha256": benchmark_sha,
            }
        ),
        encoding="utf-8",
    )
    return (
        build_benchmark_review_report(
            strategy_path,
            benchmark_path,
            metadata_path,
            block_size=4,
            n_bootstrap=100,
            random_seed=17,
        ),
        strategy_path,
    )
