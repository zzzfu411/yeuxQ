from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

from quantify.research.benchmark_report import (
    build_benchmark_review_report,
    write_benchmark_review_report,
)


def test_formal_total_return_review_records_provenance_and_passes(tmp_path: Path) -> None:
    strategy_path, benchmark_path, metadata_path = _write_review_inputs(
        tmp_path,
        active_returns=_positive_active_returns(),
    )

    report = build_benchmark_review_report(
        strategy_path,
        benchmark_path,
        metadata_path,
        block_size=4,
        n_bootstrap=250,
        random_seed=17,
    )
    output = write_benchmark_review_report(report, tmp_path / "report")
    payload = json.loads((output / "benchmark_report.json").read_text(encoding="utf-8"))

    assert report.status == "PASS"
    assert report.sufficient is True
    assert report.identity is not None and report.identity.total_return is True
    assert report.metrics is not None and report.metrics.excess_cagr > 0.0
    assert report.annualized_excess_return_ci is not None
    assert report.annualized_excess_return_ci.lower > 0.0
    assert payload["artifact_type"] == "benchmark_report"
    assert payload["evidence_role"] == "benchmark_evidence_only"
    assert payload["can_upgrade_deterministic_gate"] is False
    assert payload["inputs"]["strategy_equity_csv"]["sha256"] == _sha256(strategy_path)
    assert payload["inputs"]["benchmark_csv"]["sha256"] == _sha256(benchmark_path)
    assert payload["inputs"]["benchmark_csv"]["sha256_matches_metadata"] is True
    assert payload["inputs"]["strategy_equity_csv"]["start_date"] == "2024-01-01"
    assert payload["inputs"]["strategy_equity_csv"]["end_date"] == "2024-02-10"
    assert payload["inputs"]["benchmark_csv"]["start_date"] == "2024-01-02"
    assert payload["inputs"]["benchmark_csv"]["end_date"] == "2024-02-10"
    assert payload["inputs"]["benchmark_metadata_json"]["sha256"] == _sha256(metadata_path)
    assert payload["identity"] == {
        "symbol": "000300.SH",
        "name": "CSI 300 Total Return",
        "total_return": True,
    }
    assert payload["alignment"]["aligned_observations"] == 40
    assert payload["metrics"]["annualized_tracking_error"] is not None
    assert payload["metrics"]["information_ratio"] is not None
    markdown = (output / "benchmark_report.md").read_text(encoding="utf-8")
    assert "cannot upgrade, satisfy, or bypass any deterministic gate" in markdown


def test_excess_return_interval_crossing_zero_is_watch(tmp_path: Path) -> None:
    active = np.tile(np.array([-0.004, 0.004, -0.003, 0.003]), 10)
    strategy_path, benchmark_path, metadata_path = _write_review_inputs(
        tmp_path,
        active_returns=active,
    )

    report = build_benchmark_review_report(
        strategy_path,
        benchmark_path,
        metadata_path,
        block_size=3,
        n_bootstrap=400,
        random_seed=23,
    )

    assert report.status == "WATCH"
    assert report.sufficient is True
    assert report.annualized_excess_return_ci is not None
    assert report.annualized_excess_return_ci.lower <= 0.0
    assert report.annualized_excess_return_ci.upper > 0.0
    assert any(item.code == "EXCESS_RETURN_CI_CROSSES_ZERO" for item in report.evidence)


def test_non_positive_excess_return_interval_is_statistical_block(tmp_path: Path) -> None:
    active = -_positive_active_returns()
    strategy_path, benchmark_path, metadata_path = _write_review_inputs(
        tmp_path,
        active_returns=active,
    )

    report = build_benchmark_review_report(
        strategy_path,
        benchmark_path,
        metadata_path,
        block_size=4,
        n_bootstrap=250,
        random_seed=29,
    )

    assert report.status == "BLOCK"
    assert report.sufficient is True
    assert report.metrics is not None
    assert report.metrics.excess_cagr < 0.0
    assert report.annualized_excess_return_ci is not None
    assert report.annualized_excess_return_ci.upper <= 0.0
    assert any(item.code == "EXCESS_RETURN_CI_NON_POSITIVE" for item in report.evidence)


def test_benchmark_sha256_mismatch_blocks_without_statistics(tmp_path: Path) -> None:
    strategy_path, benchmark_path, metadata_path = _write_review_inputs(
        tmp_path,
        active_returns=_positive_active_returns(),
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["file_sha256"] = "0" * 64
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    report = build_benchmark_review_report(strategy_path, benchmark_path, metadata_path)
    payload = report.to_dict()

    assert report.status == "BLOCK"
    assert report.sufficient is False
    assert report.metrics is None
    assert payload["alignment"] is None
    assert all(value is None for value in payload["metrics"].values())
    assert payload["confidence_intervals"] == {
        "annualized_excess_return_95": None,
        "information_ratio_95": None,
    }
    assert any(item.code == "BENCHMARK_SHA256_MISMATCH" for item in report.evidence)


def test_price_return_metadata_is_blocked_as_incomplete_evidence(tmp_path: Path) -> None:
    strategy_path, benchmark_path, metadata_path = _write_review_inputs(
        tmp_path,
        active_returns=_positive_active_returns(),
        total_return=False,
    )

    report = build_benchmark_review_report(strategy_path, benchmark_path, metadata_path)

    assert report.status == "BLOCK"
    assert report.sufficient is False
    assert report.identity is not None and report.identity.total_return is False
    assert report.metrics is None
    assert any(
        item.code == "BENCHMARK_METADATA_TOTAL_RETURN_REQUIRED" for item in report.evidence
    )


def test_cli_writes_block_report_and_returns_two_for_missing_metadata_field(
    tmp_path: Path,
) -> None:
    strategy_path, benchmark_path, metadata_path = _write_review_inputs(
        tmp_path,
        active_returns=_positive_active_returns(),
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    del metadata["reviewed_by"]
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    output = tmp_path / "blocked"

    completed = _run_cli(strategy_path, benchmark_path, metadata_path, output)
    payload = json.loads((output / "benchmark_report.json").read_text(encoding="utf-8"))

    assert completed.returncode == 2, completed.stderr
    assert payload["status"] == "BLOCK"
    assert payload["sufficient"] is False
    assert payload["metrics"]["excess_cagr"] is None
    assert (output / "benchmark_report.md").exists()


def test_cli_returns_nonzero_and_writes_no_report_for_unparseable_json(
    tmp_path: Path,
) -> None:
    strategy_path, benchmark_path, metadata_path = _write_review_inputs(
        tmp_path,
        active_returns=_positive_active_returns(),
    )
    metadata_path.write_text('{"artifact_type":', encoding="utf-8")
    output = tmp_path / "parse_error"

    completed = _run_cli(strategy_path, benchmark_path, metadata_path, output)

    assert completed.returncode == 2
    assert "Benchmark review input error" in completed.stderr
    assert not (output / "benchmark_report.json").exists()
    assert not (output / "benchmark_report.md").exists()


def _write_review_inputs(
    root: Path,
    *,
    active_returns: np.ndarray,
    total_return: bool = True,
) -> tuple[Path, Path, Path]:
    dates = pd.date_range("2024-01-01", periods=len(active_returns) + 1, freq="D")
    benchmark_returns = np.tile(
        np.array([0.0010, -0.0008, 0.0015, 0.0002, -0.0004]),
        8,
    )[: len(active_returns)]
    strategy_returns = benchmark_returns + active_returns
    strategy_equity = 100_000.0 * np.cumprod(np.concatenate(([1.0], 1.0 + strategy_returns)))

    strategy_path = root / "strategy_equity.csv"
    benchmark_path = root / "benchmark.csv"
    metadata_path = root / "benchmark_metadata.json"
    pd.DataFrame({"timestamp": dates, "equity": strategy_equity}).to_csv(
        strategy_path,
        index=False,
    )
    pd.DataFrame({"date": dates[1:], "value": benchmark_returns}).to_csv(
        benchmark_path,
        index=False,
    )
    metadata = {
        "artifact_type": "reviewed_benchmark_series",
        "schema_version": 1,
        "symbol": "000300.SH",
        "name": "CSI 300 Total Return",
        "total_return": total_return,
        "series_kind": "returns",
        "source_vendor": "licensed-test-vendor",
        "source_exported_at": "2026-07-15T09:30:00+08:00",
        "reviewed_by": "research-operator",
        "reviewed_at": "2026-07-15T10:00:00+08:00",
        "file_sha256": _sha256(benchmark_path),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return strategy_path, benchmark_path, metadata_path


def _positive_active_returns() -> np.ndarray:
    return np.tile(np.array([0.0010, 0.0018, 0.0026, 0.0014, 0.0022]), 8)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_cli(
    strategy_path: Path,
    benchmark_path: Path,
    metadata_path: Path,
    output: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "examples/run_benchmark_review.py",
            "--strategy-equity-csv",
            str(strategy_path),
            "--benchmark-csv",
            str(benchmark_path),
            "--benchmark-metadata",
            str(metadata_path),
            "--output-dir",
            str(output),
            "--block-size",
            "4",
            "--n-bootstrap",
            "100",
            "--random-seed",
            "31",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
