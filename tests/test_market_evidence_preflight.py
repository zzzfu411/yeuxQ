from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from quantify.data.market_evidence_preflight import (
    build_market_evidence_preflight,
    write_market_evidence_preflight,
)


def test_valid_reviewed_market_evidence_passes_and_records_hashes(tmp_path: Path) -> None:
    paths = _write_valid_evidence(tmp_path)

    report = _build(paths)
    output = write_market_evidence_preflight(report, tmp_path / "report")
    payload = json.loads((output / "market_evidence_preflight.json").read_text(encoding="utf-8"))

    assert report.status == "PASS"
    assert report.sufficient is True
    assert payload["operation"] == "read_only_external_evidence_validation"
    assert payload["network_access"] is False
    assert payload["broker_access"] is False
    assert payload["expected_index_code"] == "000906"
    assert payload["minimum_members_per_snapshot"] == 2
    assert payload["benchmark"]["csv"]["sha256"] == _sha256(paths["benchmark_csv"])
    assert payload["benchmark"]["csv"]["sha256_matches_metadata"] is True
    assert payload["membership"]["csv"]["sha256"] == _sha256(paths["membership_csv"])
    assert payload["membership"]["csv"]["sha256_matches_metadata"] is True
    assert payload["membership"]["csv"]["effective_dates"] == 3
    assert payload["membership"]["metadata"]["snapshot_mode"] == "point_in_time_history"
    markdown = (output / "market_evidence_preflight.md").read_text(encoding="utf-8")
    assert "Market Evidence Preflight: PASS" in markdown
    assert "does not fetch data, contact a broker, or authorize trading" in markdown


def test_missing_and_unparseable_inputs_fail_closed_without_raising(tmp_path: Path) -> None:
    paths = _write_valid_evidence(tmp_path)
    paths["benchmark_metadata"].write_text('{"artifact_type":', encoding="utf-8")
    paths["membership_csv"].unlink()

    report = _build(paths)

    assert report.status == "BLOCK"
    assert report.sufficient is False
    assert _has_code(report, "BENCHMARK_METADATA_JSON_INVALID")
    assert _has_code(report, "MEMBERSHIP_CSV_MISSING")
    assert report.membership_csv.sha256_matches_metadata is None


@pytest.mark.parametrize(
    ("target", "expected_code"),
    [
        ("benchmark_csv", "BENCHMARK_SHA256_MISMATCH"),
        ("membership_csv", "MEMBERSHIP_SHA256_MISMATCH"),
    ],
)
def test_csv_hash_mismatch_blocks(
    tmp_path: Path,
    target: str,
    expected_code: str,
) -> None:
    paths = _write_valid_evidence(tmp_path)
    with paths[target].open("a", encoding="utf-8") as handle:
        handle.write("\n")

    report = _build(paths)

    assert report.status == "BLOCK"
    assert _has_code(report, expected_code)


def test_non_total_return_or_wrong_benchmark_index_blocks(tmp_path: Path) -> None:
    paths = _write_valid_evidence(tmp_path)
    metadata = _read_json(paths["benchmark_metadata"])
    metadata["total_return"] = False
    metadata["symbol"] = "000300.SH"
    _write_json(paths["benchmark_metadata"], metadata)

    report = _build(paths)

    assert report.status == "BLOCK"
    assert _has_code(report, "BENCHMARK_TOTAL_RETURN_REQUIRED")
    assert _has_code(report, "BENCHMARK_INDEX_CODE_MISMATCH")


def test_wrong_membership_index_blocks_metadata_and_rows(tmp_path: Path) -> None:
    paths = _write_valid_evidence(tmp_path)
    metadata = _read_json(paths["membership_metadata"])
    metadata["index_code"] = "000905"
    _write_json(paths["membership_metadata"], metadata)
    _replace_csv_value(paths["membership_csv"], "index_code", "000905")
    metadata["file_sha256"] = _sha256(paths["membership_csv"])
    _write_json(paths["membership_metadata"], metadata)

    report = _build(paths)

    assert report.status == "BLOCK"
    assert _has_code(report, "MEMBERSHIP_INDEX_CODE_MISMATCH")
    assert _has_code(report, "MEMBERSHIP_CSV_INDEX_CODE_MISMATCH")


@pytest.mark.parametrize(
    ("point_in_time", "snapshot_mode"),
    [(False, "point_in_time_history"), (True, "current_snapshot")],
)
def test_non_pit_or_current_snapshot_metadata_blocks(
    tmp_path: Path,
    point_in_time: bool,
    snapshot_mode: str,
) -> None:
    paths = _write_valid_evidence(tmp_path)
    metadata = _read_json(paths["membership_metadata"])
    metadata["point_in_time"] = point_in_time
    metadata["snapshot_mode"] = snapshot_mode
    _write_json(paths["membership_metadata"], metadata)

    report = _build(paths)

    assert report.status == "BLOCK"
    expected = (
        "MEMBERSHIP_NOT_POINT_IN_TIME" if not point_in_time else "MEMBERSHIP_SNAPSHOT_MODE_INVALID"
    )
    assert _has_code(report, expected)


def test_single_snapshot_duplicate_key_and_invalid_date_all_block(tmp_path: Path) -> None:
    paths = _write_valid_evidence(tmp_path)
    rows = [
        {"index_code": "000906", "effective_date": "not-a-date", "symbol": "600001"},
        {"index_code": "000906", "effective_date": "2024-01-01", "symbol": "000001"},
        {"index_code": "000906", "effective_date": "2024-01-01", "symbol": "000001"},
    ]
    _write_csv(paths["membership_csv"], rows)
    metadata = _read_json(paths["membership_metadata"])
    metadata["file_sha256"] = _sha256(paths["membership_csv"])
    _write_json(paths["membership_metadata"], metadata)

    report = _build(paths)

    assert report.status == "BLOCK"
    assert _has_code(report, "MEMBERSHIP_DATES_INVALID")
    assert _has_code(report, "MEMBERSHIP_KEYS_DUPLICATE")
    assert _has_code(report, "MEMBERSHIP_CURRENT_SNAPSHOT_ONLY")


def test_inadequate_declared_coverage_and_missing_provenance_block(tmp_path: Path) -> None:
    paths = _write_valid_evidence(tmp_path)
    benchmark = _read_json(paths["benchmark_metadata"])
    benchmark["coverage_start_date"] = "2024-02-01"
    benchmark["reviewed_by"] = "<reviewer>"
    _write_json(paths["benchmark_metadata"], benchmark)
    membership = _read_json(paths["membership_metadata"])
    membership["coverage_end_date"] = "2024-06-30"
    del membership["source_dataset"]
    _write_json(paths["membership_metadata"], membership)

    report = _build(paths)

    assert report.status == "BLOCK"
    assert _has_code(report, "BENCHMARK_DECLARED_COVERAGE_INADEQUATE")
    assert _has_code(report, "BENCHMARK_METADATA_REVIEWED_BY_INVALID")
    assert _has_code(report, "MEMBERSHIP_DECLARED_COVERAGE_INADEQUATE")
    assert _has_code(report, "MEMBERSHIP_METADATA_FIELDS_MISSING")
    assert _has_code(report, "MEMBERSHIP_METADATA_SOURCE_DATASET_INVALID")


def test_declared_and_observed_dates_after_source_export_block(tmp_path: Path) -> None:
    paths = _write_valid_evidence(tmp_path)
    for key in ("benchmark_metadata", "membership_metadata"):
        metadata = _read_json(paths[key])
        metadata["source_exported_at"] = "2024-06-01T18:00:00+08:00"
        metadata["reviewed_at"] = "2024-06-01T19:00:00+08:00"
        _write_json(paths[key], metadata)

    report = _build(paths)

    assert report.status == "BLOCK"
    assert _has_code(report, "BENCHMARK_DECLARED_COVERAGE_AFTER_EXPORT")
    assert _has_code(report, "BENCHMARK_OBSERVATION_AFTER_EXPORT")
    assert _has_code(report, "MEMBERSHIP_DECLARED_COVERAGE_AFTER_EXPORT")
    assert _has_code(report, "MEMBERSHIP_OBSERVATION_AFTER_EXPORT")


def test_duplicate_benchmark_dates_and_invalid_values_block(tmp_path: Path) -> None:
    paths = _write_valid_evidence(tmp_path)
    rows = [
        {"date": "2024-01-01", "value": "100"},
        {"date": "2024-01-01", "value": "NaN"},
        {"date": "2024-12-31", "value": "110"},
    ]
    _write_csv(paths["benchmark_csv"], rows)
    metadata = _read_json(paths["benchmark_metadata"])
    metadata["file_sha256"] = _sha256(paths["benchmark_csv"])
    _write_json(paths["benchmark_metadata"], metadata)

    report = _build(paths)

    assert report.status == "BLOCK"
    assert _has_code(report, "BENCHMARK_DATES_DUPLICATE")
    assert _has_code(report, "BENCHMARK_VALUES_INVALID")


def test_report_writer_never_overwrites_an_external_input(tmp_path: Path) -> None:
    paths = _write_valid_evidence(tmp_path)
    protected_input = tmp_path / "market_evidence_preflight.json"
    paths["benchmark_csv"].replace(protected_input)
    paths["benchmark_csv"] = protected_input
    metadata = _read_json(paths["benchmark_metadata"])
    metadata["file_sha256"] = _sha256(protected_input)
    _write_json(paths["benchmark_metadata"], metadata)
    original_bytes = protected_input.read_bytes()
    report = _build(paths)

    with pytest.raises(OSError, match="must not overwrite"):
        write_market_evidence_preflight(report, tmp_path)

    assert protected_input.read_bytes() == original_bytes


def test_cli_writes_both_reports_and_exits_two_on_block(tmp_path: Path) -> None:
    paths = _write_valid_evidence(tmp_path)
    metadata = _read_json(paths["membership_metadata"])
    metadata["point_in_time"] = False
    _write_json(paths["membership_metadata"], metadata)
    output = tmp_path / "cli-block"

    completed = _run_cli(paths, output)
    payload = json.loads((output / "market_evidence_preflight.json").read_text(encoding="utf-8"))

    assert completed.returncode == 2, completed.stderr
    assert payload["status"] == "BLOCK"
    assert (output / "market_evidence_preflight.md").is_file()


def test_cli_exits_zero_on_pass(tmp_path: Path) -> None:
    paths = _write_valid_evidence(tmp_path)
    output = tmp_path / "cli-pass"

    completed = _run_cli(paths, output)

    assert completed.returncode == 0, completed.stderr
    assert "Market evidence preflight status: PASS" in completed.stdout


def test_default_minimum_blocks_implausibly_small_csi800_snapshots(tmp_path: Path) -> None:
    paths = _write_valid_evidence(tmp_path)

    report = build_market_evidence_preflight(
        paths["benchmark_csv"],
        paths["benchmark_metadata"],
        paths["membership_csv"],
        paths["membership_metadata"],
        required_start_date="2024-01-01",
        required_end_date="2024-12-31",
    )

    assert report.status == "BLOCK"
    assert _has_code(report, "MEMBERSHIP_SNAPSHOT_MEMBER_COUNT_TOO_LOW")


def _write_valid_evidence(root: Path) -> dict[str, Path]:
    paths = {
        "benchmark_csv": root / "csi800_total_return.csv",
        "benchmark_metadata": root / "csi800_total_return.metadata.json",
        "membership_csv": root / "csi800_pit_membership.csv",
        "membership_metadata": root / "csi800_pit_membership.metadata.json",
    }
    _write_csv(
        paths["benchmark_csv"],
        [
            {"date": "2024-01-01", "value": "1000.0"},
            {"date": "2024-06-28", "value": "1035.0"},
            {"date": "2024-12-31", "value": "1080.0"},
        ],
    )
    _write_csv(
        paths["membership_csv"],
        [
            {"index_code": "000906", "effective_date": "2024-01-01", "symbol": "000001"},
            {"index_code": "000906", "effective_date": "2024-01-01", "symbol": "600001"},
            {"index_code": "000906", "effective_date": "2024-04-01", "symbol": "000001"},
            {"index_code": "000906", "effective_date": "2024-04-01", "symbol": "600002"},
            {"index_code": "000906", "effective_date": "2024-10-01", "symbol": "000001"},
            {"index_code": "000906", "effective_date": "2024-10-01", "symbol": "600003"},
        ],
    )
    _write_json(
        paths["benchmark_metadata"],
        {
            "artifact_type": "reviewed_benchmark_series",
            "schema_version": 1,
            "symbol": "000906.SH",
            "name": "CSI 800 Total Return",
            "total_return": True,
            "series_kind": "equity",
            "coverage_start_date": "2024-01-01",
            "coverage_end_date": "2024-12-31",
            "source_vendor": "licensed-test-vendor",
            "source_exported_at": "2026-07-15T09:30:00+08:00",
            "reviewed_by": "research-operator",
            "reviewed_at": "2026-07-15T10:00:00+08:00",
            "file_sha256": _sha256(paths["benchmark_csv"]),
        },
    )
    _write_json(
        paths["membership_metadata"],
        {
            "artifact_type": "reviewed_pit_universe_membership",
            "schema_version": 1,
            "index_code": "000906",
            "point_in_time": True,
            "snapshot_mode": "point_in_time_history",
            "effective_date_column": "effective_date",
            "symbol_column": "symbol",
            "index_code_column": "index_code",
            "coverage_start_date": "2024-01-01",
            "coverage_end_date": "2024-12-31",
            "source_vendor": "licensed-test-vendor",
            "source_dataset": "CSI 800 historical constituents",
            "source_exported_at": "2026-07-15T09:30:00+08:00",
            "reviewed_by": "research-operator",
            "reviewed_at": "2026-07-15T10:00:00+08:00",
            "file_sha256": _sha256(paths["membership_csv"]),
        },
    )
    return paths


def _build(paths: dict[str, Path]):
    return build_market_evidence_preflight(
        paths["benchmark_csv"],
        paths["benchmark_metadata"],
        paths["membership_csv"],
        paths["membership_metadata"],
        required_start_date="2024-01-01",
        required_end_date="2024-12-31",
        minimum_members_per_snapshot=2,
    )


def _has_code(report: Any, code: str) -> bool:
    return any(item.code == code for item in report.evidence)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _replace_csv_value(path: Path, column: str, value: str) -> None:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row[column] = value
    _write_csv(path, rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_cli(paths: dict[str, Path], output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "examples/run_market_evidence_preflight.py",
            "--benchmark-csv",
            str(paths["benchmark_csv"]),
            "--benchmark-metadata",
            str(paths["benchmark_metadata"]),
            "--membership-csv",
            str(paths["membership_csv"]),
            "--membership-metadata",
            str(paths["membership_metadata"]),
            "--required-start-date",
            "2024-01-01",
            "--required-end-date",
            "2024-12-31",
            "--output-dir",
            str(output),
            "--minimum-members-per-snapshot",
            "2",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
