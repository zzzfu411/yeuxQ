from __future__ import annotations

import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from quantify.data.exchange_calendar_preflight import (
    build_exchange_calendar_preflight,
    write_exchange_calendar_preflight,
)

EVALUATED_AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def test_complete_reviewed_calendar_passes(tmp_path: Path, monkeypatch) -> None:
    paths = _valid_calendar(tmp_path)
    _set_clock(monkeypatch)

    report = _build(paths)
    output = write_exchange_calendar_preflight(report, tmp_path / "report")

    assert report.status == "PASS", report.blockers
    assert report.sufficient is True
    assert report.calendar_day_count == 7
    assert report.open_session_count == 4
    assert report.closed_day_count == 3
    assert report.observed_start_date == "2026-07-13"
    assert report.observed_end_date == "2026-07-19"
    assert next(item for item in report.sessions if item["date"] == "2026-07-15")[
        "is_open"
    ] is False
    assert _check_status(report, "EXACT_DAILY_COVERAGE") == "PASS"
    assert _check_status(report, "WEEKEND_CLOSED") == "PASS"
    assert (output / "exchange_calendar_preflight.json").is_file()


def test_missing_inputs_fail_closed_without_raising(tmp_path: Path, monkeypatch) -> None:
    _set_clock(monkeypatch)
    paths = {
        "csv": tmp_path / "missing.csv",
        "metadata": tmp_path / "missing.metadata.json",
    }

    report = _build(paths)

    assert report.status == "BLOCK"
    assert _check_status(report, "CALENDAR_CSV_READABLE") == "BLOCK"
    assert _check_status(report, "CALENDAR_METADATA_READABLE") == "BLOCK"
    assert report.sessions == ()


def test_hash_mismatch_and_placeholder_reviewer_block(tmp_path: Path, monkeypatch) -> None:
    paths = _valid_calendar(tmp_path)
    metadata = _read_json(paths["metadata"])
    metadata["file_sha256"] = "0" * 64
    metadata["reviewed_by"] = "<reviewer>"
    _write_json(paths["metadata"], metadata)
    _set_clock(monkeypatch)

    report = _build(paths)

    assert report.status == "BLOCK"
    assert _check_status(report, "CSV_SHA256_BINDING") == "BLOCK"
    assert _check_status(report, "METADATA_PROVENANCE") == "BLOCK"


def test_missing_natural_day_blocks_even_when_required_dates_exist(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _valid_calendar(tmp_path)
    rows = _read_csv(paths["csv"])
    _write_csv(paths["csv"], [row for row in rows if row["date"] != "2026-07-16"])
    _refresh_hash(paths)
    _set_clock(monkeypatch)

    report = _build(paths)

    assert report.status == "BLOCK"
    assert _check_status(report, "EXACT_DAILY_COVERAGE") == "BLOCK"


def test_weekend_open_duplicate_and_invalid_open_value_block(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _valid_calendar(tmp_path)
    rows = _read_csv(paths["csv"])
    rows[-1]["is_open"] = "1"
    rows[2]["is_open"] = "yes"
    rows.append(dict(rows[0]))
    _write_csv(paths["csv"], rows)
    _refresh_hash(paths)
    _set_clock(monkeypatch)

    report = _build(paths)

    assert report.status == "BLOCK"
    assert _check_status(report, "CALENDAR_CSV_CONTRACT") == "BLOCK"
    assert _check_status(report, "EXACT_DAILY_COVERAGE") == "BLOCK"
    assert _check_status(report, "WEEKEND_CLOSED") == "BLOCK"


def test_extra_column_and_noncanonical_date_block(tmp_path: Path, monkeypatch) -> None:
    paths = _valid_calendar(tmp_path)
    paths["csv"].write_text(
        "date,is_open,note\n"
        "20260713,1,compact date is not canonical\n",
        encoding="utf-8",
    )
    _refresh_hash(paths)
    _set_clock(monkeypatch)

    report = _build(paths)

    assert report.status == "BLOCK"
    assert _check_status(report, "CALENDAR_CSV_CONTRACT") == "BLOCK"


def test_future_review_and_coverage_after_export_block(tmp_path: Path, monkeypatch) -> None:
    paths = _valid_calendar(tmp_path)
    metadata = _read_json(paths["metadata"])
    metadata["source_exported_at"] = "2026-07-18T18:00:00+08:00"
    metadata["reviewed_at"] = "2026-07-21T09:00:00+08:00"
    _write_json(paths["metadata"], metadata)
    _set_clock(monkeypatch)

    report = _build(paths)

    assert report.status == "BLOCK"
    assert _check_status(report, "SOURCE_REVIEW_TIMESTAMPS") == "BLOCK"
    assert _check_status(report, "EXPORT_COVERS_DECLARED_END") == "BLOCK"


def test_export_coverage_date_is_compared_in_market_timezone(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _valid_calendar(tmp_path)
    metadata = _read_json(paths["metadata"])
    metadata["source_exported_at"] = "2026-07-18T16:30:00+00:00"
    metadata["reviewed_at"] = "2026-07-18T17:00:00+00:00"
    _write_json(paths["metadata"], metadata)
    _set_clock(monkeypatch)

    report = _build(paths)

    assert report.status == "PASS", report.blockers
    assert _check_status(report, "EXPORT_COVERS_DECLARED_END") == "PASS"


def test_wrong_identity_and_inadequate_required_coverage_block(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _valid_calendar(tmp_path)
    metadata = _read_json(paths["metadata"])
    metadata["exchange_scope"] = "US_EQUITY"
    metadata["timezone"] = "UTC"
    _write_json(paths["metadata"], metadata)
    _set_clock(monkeypatch)

    report = build_exchange_calendar_preflight(
        paths["csv"],
        paths["metadata"],
        required_start_date="2026-07-12",
        required_end_date="2026-07-20",
    )

    assert report.status == "BLOCK"
    assert _check_status(report, "METADATA_IDENTITY") == "BLOCK"
    assert _check_status(report, "REQUIRED_COVERAGE_SPANNED") == "BLOCK"


def test_writer_refuses_to_overwrite_input(tmp_path: Path, monkeypatch) -> None:
    protected = tmp_path / "exchange_calendar_preflight.json"
    paths = _valid_calendar(tmp_path, csv_path=protected)
    _set_clock(monkeypatch)
    report = _build(paths)
    original = protected.read_bytes()

    with pytest.raises(OSError, match="must not overwrite"):
        write_exchange_calendar_preflight(report, tmp_path)

    assert protected.read_bytes() == original


def test_cli_writes_report_and_returns_zero_on_pass(tmp_path: Path) -> None:
    paths = _valid_calendar(tmp_path)
    historical_rows = [
        {"date": "2026-07-06", "is_open": "1"},
        {"date": "2026-07-07", "is_open": "1"},
        {"date": "2026-07-08", "is_open": "1"},
        {"date": "2026-07-09", "is_open": "1"},
        {"date": "2026-07-10", "is_open": "1"},
        {"date": "2026-07-11", "is_open": "0"},
        {"date": "2026-07-12", "is_open": "0"},
    ]
    _write_csv(paths["csv"], historical_rows)
    metadata = _read_json(paths["metadata"])
    metadata.update(
        {
            "coverage_start_date": "2026-07-06",
            "coverage_end_date": "2026-07-12",
            "source_exported_at": "2026-07-12T18:00:00+08:00",
            "reviewed_at": "2026-07-12T19:00:00+08:00",
            "file_sha256": _sha256(paths["csv"]),
        }
    )
    _write_json(paths["metadata"], metadata)
    output = tmp_path / "cli"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_exchange_calendar_preflight.py",
            "--calendar-csv",
            str(paths["csv"]),
            "--metadata",
            str(paths["metadata"]),
            "--required-start-date",
            "2026-07-07",
            "--required-end-date",
            "2026-07-10",
            "--output-dir",
            str(output),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "status: PASS" in completed.stdout
    assert (output / "exchange_calendar_preflight.json").is_file()


def _valid_calendar(
    root: Path,
    *,
    csv_path: Path | None = None,
) -> dict[str, Path]:
    paths = {
        "csv": csv_path or root / "cn_a_share_calendar.csv",
        "metadata": root / "cn_a_share_calendar.metadata.json",
    }
    rows = [
        {"date": "2026-07-13", "is_open": "1"},
        {"date": "2026-07-14", "is_open": "1"},
        {"date": "2026-07-15", "is_open": "0"},
        {"date": "2026-07-16", "is_open": "1"},
        {"date": "2026-07-17", "is_open": "1"},
        {"date": "2026-07-18", "is_open": "0"},
        {"date": "2026-07-19", "is_open": "0"},
    ]
    _write_csv(paths["csv"], rows)
    _write_json(
        paths["metadata"],
        {
            "artifact_type": "reviewed_exchange_calendar",
            "schema_version": 1,
            "exchange_scope": "CN_A_SHARE",
            "timezone": "Asia/Shanghai",
            "date_column": "date",
            "is_open_column": "is_open",
            "coverage_start_date": "2026-07-13",
            "coverage_end_date": "2026-07-19",
            "source_vendor": "licensed-test-vendor",
            "source_dataset": "China A-share exchange calendar",
            "source_exported_at": "2026-07-19T18:00:00+08:00",
            "reviewed_by": "independent-test-reviewer",
            "reviewed_at": "2026-07-19T19:00:00+08:00",
            "file_sha256": _sha256(paths["csv"]),
        },
    )
    return paths


def _build(paths: dict[str, Path]):
    return build_exchange_calendar_preflight(
        paths["csv"],
        paths["metadata"],
        required_start_date="2026-07-14",
        required_end_date="2026-07-17",
    )


def _set_clock(monkeypatch) -> None:
    monkeypatch.setattr(
        "quantify.data.exchange_calendar_preflight._runtime_now",
        lambda: EVALUATED_AT,
    )


def _check_status(report, code: str) -> str:
    return next(item.status for item in report.checks if item.code == code)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("date", "is_open"))
        writer.writeheader()
        writer.writerows(rows)


def _refresh_hash(paths: dict[str, Path]) -> None:
    metadata = _read_json(paths["metadata"])
    metadata["file_sha256"] = _sha256(paths["csv"])
    _write_json(paths["metadata"], metadata)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
