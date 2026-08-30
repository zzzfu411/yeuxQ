from __future__ import annotations

import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from examples.run_prospective_daily_acquisition import main as acquisition_main
from examples.verify_prospective_acquisition_attempts import main as verify_attempts_main
from quantify.data.akshare_feed import AkshareFeed
from quantify.data.prospective_daily_acquisition import (
    build_prospective_daily_acquisition_preflight,
    handoff_prospective_daily_acquisition,
    run_prospective_daily_acquisition,
)
from quantify.data.prospective_acquisition_journal import (
    ATTEMPT_LEDGER_FILENAME,
    ProspectiveAcquisitionJournalError,
    record_prospective_acquisition_attempt,
    verify_prospective_acquisition_attempts,
)
from quantify.data.storage import BarStorage
from quantify.research.prospective_trial_packet import (
    append_packet_preregistration,
    build_prospective_trial_packet,
    write_prospective_trial_packet,
)
from quantify.research.sealed_holdout_intake import verify_collection_ledger

REGISTRATION_TIME = datetime(2026, 7, 16, 0, 0, tzinfo=UTC)
AFTER_CLOSE = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
BEFORE_CLOSE = datetime(2026, 7, 16, 21, 0, tzinfo=UTC)
MONDAY_BEFORE_CLOSE = datetime(2026, 7, 19, 21, 0, tzinfo=UTC)
MONDAY_AFTER_CLOSE = datetime(2026, 7, 20, 8, 0, tzinfo=UTC)
SYMBOLS = ("000001", "300001", "600001")


def test_premarket_preflight_blocks_without_creating_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    output = tmp_path / "quarantine"
    _set_acquisition_clock(monkeypatch, BEFORE_CLOSE)

    report = _preflight(paths, output)

    assert report.status == "BLOCK"
    assert report.fetch_allowed is False
    assert _check_status(report, "PACKET_INTEGRITY") == "PASS"
    assert _check_status(report, "FROZEN_UNIVERSE") == "PASS"
    assert _check_status(report, "POST_CLOSE_TIME") == "BLOCK"
    assert report.frozen_symbol_count == 3
    assert report.requested_symbols == 0
    assert report.execution_cache_write_allowed is False
    assert report.holdout_analysis_allowed is False
    assert not output.exists()


def test_reviewed_market_closed_date_is_noop_before_close(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    output = tmp_path / "quarantine"
    calendar = _reviewed_calendar(tmp_path, monday_open=False)
    cache_hash_before = _sha256(paths["cache"])
    _set_acquisition_clock(monkeypatch, MONDAY_BEFORE_CLOSE)
    _set_calendar_clock(monkeypatch, MONDAY_BEFORE_CLOSE)

    report = _preflight(
        paths,
        output,
        market_date="2026-07-20",
        calendar_csv=calendar["csv"],
        calendar_metadata=calendar["metadata"],
    )

    assert report.status == "MARKET_CLOSED", report.blockers
    assert report.fetch_allowed is False
    assert report.calendar_evidence_status == "PASS"
    assert report.calendar_session_status == "CLOSED"
    assert report.requested_symbols == 0
    assert report.to_dict()["network_access"] is False
    assert _check_status(report, "POST_CLOSE_TIME") == "PASS"
    assert _check_status(report, "REVIEWED_MARKET_CLOSED_EMPTY") == "PASS"
    with pytest.raises(ProspectiveAcquisitionJournalError, match="completed PASS/BLOCK"):
        record_prospective_acquisition_attempt(report, output)
    assert _sha256(paths["cache"]) == cache_hash_before
    assert not output.exists()


def test_reviewed_open_session_is_ready_after_close(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    output = tmp_path / "quarantine"
    calendar = _reviewed_calendar(tmp_path, monday_open=True)
    _set_acquisition_clock(monkeypatch, MONDAY_AFTER_CLOSE)
    _set_calendar_clock(monkeypatch, MONDAY_AFTER_CLOSE)

    report = _preflight(
        paths,
        output,
        market_date="2026-07-20",
        calendar_csv=calendar["csv"],
        calendar_metadata=calendar["metadata"],
    )

    assert report.status == "READY", report.blockers
    assert report.fetch_allowed is True
    assert report.calendar_evidence_status == "PASS"
    assert report.calendar_session_status == "OPEN"
    assert report.calendar_preflight is not None
    assert _check_status(report, "REVIEWED_CALENDAR_EVIDENCE") == "PASS"

    def fetch(symbol: str, start: str, end: str):
        return _provider_frame(symbol, start), "eastmoney"

    acquisition = run_prospective_daily_acquisition(
        report,
        output_dir=output,
        fetch_symbol=fetch,
        retry_delay_seconds=0,
    )
    event = record_prospective_acquisition_attempt(acquisition, output)
    assert event["calendar_evidence_status"] == "PASS"
    assert event["calendar_session_status"] == "OPEN"
    assert acquisition.calendar_preflight is not None
    assert event["calendar_csv_sha256"] == acquisition.calendar_preflight.csv_sha256
    assert event["calendar_metadata_sha256"] == (
        acquisition.calendar_preflight.metadata_sha256
    )


def test_incomplete_or_invalid_reviewed_calendar_blocks_preflight(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    calendar = _reviewed_calendar(tmp_path, monday_open=True)
    _set_acquisition_clock(monkeypatch, MONDAY_AFTER_CLOSE)
    _set_calendar_clock(monkeypatch, MONDAY_AFTER_CLOSE)

    incomplete = _preflight(
        paths,
        tmp_path / "quarantine",
        market_date="2026-07-20",
        calendar_csv=calendar["csv"],
    )
    metadata = json.loads(calendar["metadata"].read_text(encoding="utf-8"))
    metadata["file_sha256"] = "0" * 64
    calendar["metadata"].write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    invalid = _preflight(
        paths,
        tmp_path / "quarantine",
        market_date="2026-07-20",
        calendar_csv=calendar["csv"],
        calendar_metadata=calendar["metadata"],
    )

    assert incomplete.status == "BLOCK"
    assert incomplete.fetch_allowed is False
    assert incomplete.calendar_evidence_status == "BLOCK"
    assert _check_status(incomplete, "REVIEWED_CALENDAR_INPUT_PAIR") == "BLOCK"
    assert invalid.status == "BLOCK"
    assert invalid.fetch_allowed is False
    assert invalid.calendar_evidence_status == "BLOCK"
    assert invalid.calendar_preflight is not None
    assert invalid.calendar_preflight.status == "BLOCK"


def test_calendar_mutation_and_output_root_change_block_before_fetch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    output = tmp_path / "quarantine"
    calendar = _reviewed_calendar(tmp_path, monday_open=True)
    _set_acquisition_clock(monkeypatch, MONDAY_AFTER_CLOSE)
    _set_calendar_clock(monkeypatch, MONDAY_AFTER_CLOSE)
    called: list[str] = []

    def fetch(symbol: str, start: str, end: str):
        called.append(symbol)
        return _provider_frame(symbol, start), "eastmoney"

    preflight = _preflight(
        paths,
        output,
        market_date="2026-07-20",
        calendar_csv=calendar["csv"],
        calendar_metadata=calendar["metadata"],
    )
    calendar["csv"].write_text(
        calendar["csv"].read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="calendar evidence changed"):
        run_prospective_daily_acquisition(
            preflight,
            output_dir=output,
            fetch_symbol=fetch,
            retry_delay_seconds=0,
        )
    assert called == []
    assert not output.exists()

    calendar = _reviewed_calendar(tmp_path, monday_open=True)
    preflight = _preflight(
        paths,
        output,
        market_date="2026-07-20",
        calendar_csv=calendar["csv"],
        calendar_metadata=calendar["metadata"],
    )
    changed_output = tmp_path / "different-quarantine"
    with pytest.raises(ValueError, match="output_dir changed after preflight"):
        run_prospective_daily_acquisition(
            preflight,
            output_dir=changed_output,
            fetch_symbol=fetch,
            retry_delay_seconds=0,
        )
    assert called == []
    assert not changed_output.exists()

    acquisition = run_prospective_daily_acquisition(
        preflight,
        output_dir=output,
        fetch_symbol=fetch,
        retry_delay_seconds=0,
    )
    metadata = json.loads(calendar["metadata"].read_text(encoding="utf-8"))
    metadata["reviewed_by"] = "changed-after-acquisition"
    calendar["metadata"].write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match=r"calendar evidence .*changed"):
        handoff_prospective_daily_acquisition(
            acquisition,
            packet_dir=paths["packet_dir"],
            trial_registry_path=paths["registry"],
            output_dir=output,
        )
    assert not output.exists()

    calendar = _reviewed_calendar(tmp_path, monday_open=True)
    preflight = _preflight(
        paths,
        output,
        market_date="2026-07-20",
        calendar_csv=calendar["csv"],
        calendar_metadata=calendar["metadata"],
    )
    acquisition = run_prospective_daily_acquisition(
        preflight,
        output_dir=output,
        fetch_symbol=fetch,
        retry_delay_seconds=0,
    )
    with pytest.raises(ValueError, match="output_dir changed after preflight"):
        handoff_prospective_daily_acquisition(
            acquisition,
            packet_dir=paths["packet_dir"],
            trial_registry_path=paths["registry"],
            output_dir=changed_output,
        )
    assert not changed_output.exists()


def test_reviewed_closed_date_with_retained_bars_blocks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    output = tmp_path / "quarantine"
    _set_acquisition_clock(monkeypatch, MONDAY_AFTER_CLOSE)
    _set_intake_clock(monkeypatch, MONDAY_AFTER_CLOSE)

    def fetch(symbol: str, start: str, end: str):
        return _provider_frame(symbol, start), "eastmoney"

    acquisition = run_prospective_daily_acquisition(
        _preflight(paths, output, market_date="2026-07-20"),
        output_dir=output,
        fetch_symbol=fetch,
        retry_delay_seconds=0,
    )
    handoff_prospective_daily_acquisition(
        acquisition,
        packet_dir=paths["packet_dir"],
        trial_registry_path=paths["registry"],
        output_dir=output,
    )
    calendar = _reviewed_calendar(tmp_path, monday_open=False)
    _set_calendar_clock(monkeypatch, MONDAY_AFTER_CLOSE)

    report = _preflight(
        paths,
        output,
        market_date="2026-07-20",
        calendar_csv=calendar["csv"],
        calendar_metadata=calendar["metadata"],
    )

    assert report.status == "BLOCK"
    assert report.existing_event is not None
    assert _check_status(report, "REVIEWED_MARKET_CLOSED_EMPTY") == "BLOCK"


def test_cli_reviewed_market_closed_is_zero_write_noop(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    output = tmp_path / "quarantine"
    calendar = _reviewed_calendar(tmp_path, monday_open=False)
    _set_acquisition_clock(monkeypatch, MONDAY_BEFORE_CLOSE)
    _set_calendar_clock(monkeypatch, MONDAY_BEFORE_CLOSE)

    exit_code = acquisition_main(
        [
            "--packet-dir",
            str(paths["packet_dir"]),
            "--registry",
            str(paths["registry"]),
            "--output-dir",
            str(output),
            "--market-date",
            "2026-07-20",
            "--calendar-csv",
            str(calendar["csv"]),
            "--calendar-metadata",
            str(calendar["metadata"]),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "status: MARKET_CLOSED" in captured.out
    assert "Report: not written" in captured.out
    assert not output.exists()


def test_cli_success_records_attempt_before_sealed_handoff(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    output = tmp_path / "quarantine"
    _set_acquisition_clock(monkeypatch, AFTER_CLOSE)
    _set_intake_clock(monkeypatch, AFTER_CLOSE)

    def fake_fetch(self, symbol, start, end):
        self.fetch_routes[symbol] = "eastmoney"
        return _provider_frame(symbol, start)

    monkeypatch.setattr(AkshareFeed, "fetch", fake_fetch)
    exit_code = acquisition_main(
        [
            "--packet-dir",
            str(paths["packet_dir"]),
            "--registry",
            str(paths["registry"]),
            "--output-dir",
            str(output),
            "--market-date",
            "2026-07-17",
            "--max-attempts",
            "1",
            "--retry-delay-seconds",
            "0",
        ]
    )

    captured = capsys.readouterr()
    events = verify_prospective_acquisition_attempts(output)
    assert exit_code == 0
    assert "Acquisition attempt journaled: sequence=1" in captured.out
    assert len(events) == 1
    assert events[0]["status"] == "PASS"
    assert len(verify_collection_ledger(output / "sealed_holdout_collection.jsonl")) == 1


def test_default_fetch_uses_nonpersistent_scratch_cache_and_deterministic_csv(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    output = tmp_path / "quarantine"
    _set_acquisition_clock(monkeypatch, AFTER_CLOSE)
    preflight = _preflight(paths, output)
    cache_hash_before = _sha256(paths["cache"])
    observed: list[tuple[str, bool, object]] = []

    def fake_fetch(self, symbol, start, end):
        observed.append((symbol, self.persist, self.storage))
        self.fetch_routes[symbol] = "eastmoney"
        return _provider_frame(symbol, start)

    monkeypatch.setattr(AkshareFeed, "fetch", fake_fetch)

    report = run_prospective_daily_acquisition(
        preflight,
        output_dir=output,
        retry_delay_seconds=0,
    )

    assert preflight.status == "READY"
    assert report.status == "PASS", report.blockers
    assert report.requested_symbols == 3
    assert report.successful_symbols == 3
    assert report.success_ratio == 1.0
    assert report.provider_routes == {"eastmoney": 3}
    assert report.row_count == 3
    assert _check_status(report, "PROVIDER_COVERAGE") == "PASS"
    assert report.csv_sha256 == hashlib.sha256(report.csv_bytes).hexdigest()
    lines = report.csv_bytes.decode("utf-8").splitlines()
    assert lines[0] == "symbol,date,open,high,low,close,volume,amount"
    assert [line.split(",", 1)[0] for line in lines[1:]] == list(SYMBOLS)
    assert all(persist is False for _, persist, _ in observed)
    assert all(storage is None for _, _, storage in observed)
    assert _sha256(paths["cache"]) == cache_hash_before
    event = record_prospective_acquisition_attempt(report, output)
    assert event["status"] == "PASS"
    assert event["previous_hash"] == "0" * 64
    assert event["requested_symbols"] == 3
    repeated = record_prospective_acquisition_attempt(report, output)
    events = verify_prospective_acquisition_attempts(output)
    assert repeated["sequence"] == 2
    assert repeated["previous_hash"] == event["event_hash"]
    assert len(events) == 2
    assert (output / ATTEMPT_LEDGER_FILENAME).is_file()


def test_provider_retries_and_blocks_below_required_coverage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    output = tmp_path / "quarantine"
    _set_acquisition_clock(monkeypatch, AFTER_CLOSE)
    preflight = _preflight(paths, output, minimum_success_ratio=0.8)
    attempts: dict[str, int] = {}

    def fetch(symbol: str, start: str, end: str):
        attempts[symbol] = attempts.get(symbol, 0) + 1
        if symbol in {"300001", "600001"}:
            raise ConnectionError("provider unavailable")
        return _provider_frame(symbol, start), "sina"

    report = run_prospective_daily_acquisition(
        preflight,
        output_dir=output,
        fetch_symbol=fetch,
        max_attempts=2,
        retry_delay_seconds=0,
    )

    assert report.status == "BLOCK"
    assert report.successful_symbols == 1
    assert report.failed_symbols == 2
    assert report.success_ratio == 1 / 3
    assert attempts == {"000001": 1, "300001": 2, "600001": 2}
    assert all(item.attempts == 2 for item in report.failures)
    assert _check_status(report, "PROVIDER_COVERAGE") == "BLOCK"
    assert report.csv_bytes
    assert report.fetch_allowed is False
    event = record_prospective_acquisition_attempt(report, output)
    assert event["status"] == "BLOCK"
    assert event["failure_count"] == 2
    assert event["successful_symbols"] == 1
    assert len(verify_prospective_acquisition_attempts(output)) == 1


def test_tampered_attempt_report_is_detected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    output = tmp_path / "quarantine"
    _set_acquisition_clock(monkeypatch, AFTER_CLOSE)

    def fetch(symbol: str, start: str, end: str):
        return _provider_frame(symbol, start), "eastmoney"

    report = run_prospective_daily_acquisition(
        _preflight(paths, output),
        output_dir=output,
        fetch_symbol=fetch,
        retry_delay_seconds=0,
    )
    event = record_prospective_acquisition_attempt(report, output)
    attempt_report = output / event["report_relative_path"]
    attempt_report.write_bytes(attempt_report.read_bytes() + b"\n")

    with pytest.raises(ProspectiveAcquisitionJournalError, match="report hash mismatch"):
        verify_prospective_acquisition_attempts(output)
    blocked = _preflight(paths, output)
    assert blocked.status == "BLOCK"
    assert blocked.fetch_allowed is False
    assert _check_status(blocked, "ACQUISITION_ATTEMPT_JOURNAL") == "BLOCK"


def test_tampered_attempt_ledger_is_detected(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    output = tmp_path / "quarantine"
    _set_acquisition_clock(monkeypatch, AFTER_CLOSE)

    def fetch(symbol: str, start: str, end: str):
        return _provider_frame(symbol, start), "eastmoney"

    report = run_prospective_daily_acquisition(
        _preflight(paths, output),
        output_dir=output,
        fetch_symbol=fetch,
        retry_delay_seconds=0,
    )
    record_prospective_acquisition_attempt(report, output)
    assert verify_attempts_main(["--output-dir", str(output)]) == 0
    assert "journal: PASS" in capsys.readouterr().out
    ledger = output / ATTEMPT_LEDGER_FILENAME
    event = json.loads(ledger.read_text(encoding="utf-8"))
    event["row_count"] = 999
    ledger.write_bytes(
        (
            json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
    )

    with pytest.raises(ProspectiveAcquisitionJournalError, match="event hash mismatch"):
        verify_prospective_acquisition_attempts(output)
    assert verify_attempts_main(["--output-dir", str(output)]) == 2
    assert "journal: BLOCK" in capsys.readouterr().err


def test_pass_acquisition_handoffs_to_quarantine_and_becomes_idempotent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    output = tmp_path / "quarantine"
    _set_acquisition_clock(monkeypatch, AFTER_CLOSE)
    _set_intake_clock(monkeypatch, AFTER_CLOSE)
    cache_hash_before = _sha256(paths["cache"])

    def fetch(symbol: str, start: str, end: str):
        route = "eastmoney" if symbol != "600001" else "sina"
        return _provider_frame(symbol, start), route

    acquisition = run_prospective_daily_acquisition(
        _preflight(paths, output),
        output_dir=output,
        fetch_symbol=fetch,
        retry_delay_seconds=0,
    )
    intake = handoff_prospective_daily_acquisition(
        acquisition,
        packet_dir=paths["packet_dir"],
        trial_registry_path=paths["registry"],
        output_dir=output,
    )

    assert acquisition.status == "PASS"
    assert intake.status == "PASS"
    assert intake.retained is True
    assert intake.execution_cache_write_allowed is False
    assert intake.holdout_analysis_allowed is False
    assert intake.source_vendor == "akshare"
    manifest_text, manifest_hash = intake.source_reference.rsplit("|sha256=", 1)
    assert Path(manifest_text).is_file()
    assert _sha256(Path(manifest_text)) == manifest_hash
    assert len(list((output / "acquisition_inputs").glob("*.csv"))) == 1
    assert len(list((output / "acquisition_reports").glob("*.json"))) == 1
    assert len(verify_collection_ledger(output / "sealed_holdout_collection.jsonl")) == 1
    assert _sha256(paths["cache"]) == cache_hash_before

    repeated = _preflight(paths, output)
    assert repeated.status == "ALREADY_RETAINED"
    assert repeated.fetch_allowed is False
    assert repeated.existing_event is not None


def test_provider_frame_with_wrong_date_is_a_failed_symbol(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    output = tmp_path / "quarantine"
    _set_acquisition_clock(monkeypatch, AFTER_CLOSE)

    def fetch(symbol: str, start: str, end: str):
        return _provider_frame(symbol, "2026-07-16"), "eastmoney"

    report = run_prospective_daily_acquisition(
        _preflight(paths, output),
        output_dir=output,
        fetch_symbol=fetch,
        max_attempts=1,
        retry_delay_seconds=0,
    )

    assert report.status == "BLOCK"
    assert report.failed_symbols == 3
    assert not report.csv_bytes
    assert all("symbol/date" in item.reason for item in report.failures)


def test_tampered_acquisition_manifest_blocks_later_preflight(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    output = tmp_path / "quarantine"
    _set_acquisition_clock(monkeypatch, AFTER_CLOSE)
    _set_intake_clock(monkeypatch, AFTER_CLOSE)

    def fetch(symbol: str, start: str, end: str):
        return _provider_frame(symbol, start), "eastmoney"

    acquisition = run_prospective_daily_acquisition(
        _preflight(paths, output),
        output_dir=output,
        fetch_symbol=fetch,
        retry_delay_seconds=0,
    )
    intake = handoff_prospective_daily_acquisition(
        acquisition,
        packet_dir=paths["packet_dir"],
        trial_registry_path=paths["registry"],
        output_dir=output,
    )
    manifest_text, _ = intake.source_reference.rsplit("|sha256=", 1)
    manifest = Path(manifest_text)
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    _set_acquisition_clock(monkeypatch, datetime(2026, 7, 20, 8, 0, tzinfo=UTC))

    report = _preflight(paths, output, market_date="2026-07-20")

    assert report.status == "BLOCK"
    assert report.fetch_allowed is False
    assert _check_status(report, "QUARANTINE_LEDGER") == "BLOCK"
    assert any("source-reference hash mismatch" in item for item in report.blockers)


def test_date_outside_frozen_interval_blocks_preflight(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    _set_acquisition_clock(monkeypatch, datetime(2026, 7, 20, 8, 0, tzinfo=UTC))

    report = _preflight(paths, tmp_path / "quarantine", market_date="2026-07-16")

    assert report.status == "BLOCK"
    assert report.fetch_allowed is False
    assert _check_status(report, "FROZEN_MARKET_DATE") == "BLOCK"


def _registered_trial(tmp_path: Path, monkeypatch) -> dict[str, Path]:
    monkeypatch.setattr(
        "quantify.research.prospective_trial_packet._runtime_now",
        lambda: REGISTRATION_TIME,
    )
    cache = tmp_path / "development.db"
    BarStorage(cache).save_bars(_development_bars())
    plan = _write_plan(tmp_path / "protocol_plan.json")
    config = _write_config(tmp_path / "base.yaml", cache)
    code = tmp_path / "frozen_candidate.py"
    code.write_text("VALUE = 1\n", encoding="utf-8")
    packet = build_prospective_trial_packet(
        plan_path=plan,
        base_config_path=config,
        development_cache_path=cache,
        execution_cache_path=cache,
        trial_id="guard-v1-acquisition-test",
        candidate="liquidity_neutral_momentum_guard_price_volume",
        train_start="2024-06-03",
        train_end="2025-06-30",
        selection_start="2025-07-01",
        selection_end="2026-07-14",
        test_start="2026-07-17",
        test_end="2026-10-16",
        code_paths=[code],
    )
    assert packet.registry_append_allowed is True, packet.blockers
    packet_dir = write_prospective_trial_packet(packet, tmp_path / "packet")
    (packet_dir / "protocol_plan.json").write_bytes(plan.read_bytes())
    registry = tmp_path / "registry.jsonl"
    append_packet_preregistration(packet, registry)
    return {"packet_dir": packet_dir, "registry": registry, "cache": cache}


def _preflight(
    paths: dict[str, Path],
    output: Path,
    *,
    market_date: str | None = "2026-07-17",
    minimum_success_ratio: float = 0.95,
    calendar_csv: Path | None = None,
    calendar_metadata: Path | None = None,
):
    return build_prospective_daily_acquisition_preflight(
        packet_dir=paths["packet_dir"],
        trial_registry_path=paths["registry"],
        output_dir=output,
        market_date=market_date,
        minimum_success_ratio=minimum_success_ratio,
        calendar_csv=calendar_csv,
        calendar_metadata=calendar_metadata,
    )


def _set_acquisition_clock(monkeypatch, value: datetime) -> None:
    monkeypatch.setattr(
        "quantify.data.prospective_daily_acquisition._runtime_now",
        lambda: value,
    )


def _set_intake_clock(monkeypatch, value: datetime) -> None:
    monkeypatch.setattr(
        "quantify.research.sealed_holdout_intake._runtime_now",
        lambda: value,
    )


def _set_calendar_clock(monkeypatch, value: datetime) -> None:
    monkeypatch.setattr(
        "quantify.data.exchange_calendar_preflight._runtime_now",
        lambda: value,
    )


def _reviewed_calendar(root: Path, *, monday_open: bool) -> dict[str, Path]:
    csv_path = root / "reviewed_exchange_calendar.csv"
    metadata_path = root / "reviewed_exchange_calendar.metadata.json"
    rows = [
        {"date": "2026-07-17", "is_open": "1"},
        {"date": "2026-07-18", "is_open": "0"},
        {"date": "2026-07-19", "is_open": "0"},
        {"date": "2026-07-20", "is_open": "1" if monday_open else "0"},
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("date", "is_open"))
        writer.writeheader()
        writer.writerows(rows)
    metadata_path.write_text(
        json.dumps(
            {
                "artifact_type": "reviewed_exchange_calendar",
                "schema_version": 1,
                "exchange_scope": "CN_A_SHARE",
                "timezone": "Asia/Shanghai",
                "date_column": "date",
                "is_open_column": "is_open",
                "coverage_start_date": "2026-07-17",
                "coverage_end_date": "2026-07-20",
                "source_vendor": "licensed-test-vendor",
                "source_dataset": "reviewed-test-calendar",
                "source_exported_at": "2026-07-20T00:05:00+08:00",
                "reviewed_by": "independent-test-reviewer",
                "reviewed_at": "2026-07-20T00:10:00+08:00",
                "file_sha256": _sha256(csv_path),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"csv": csv_path, "metadata": metadata_path}


def _provider_frame(symbol: str, market_date: str) -> pd.DataFrame:
    close = 10.0 + int(symbol[-1]) * 0.1
    return pd.DataFrame(
        {
            "symbol": [symbol],
            "date": [market_date],
            "open": [close],
            "high": [close + 0.5],
            "low": [close - 0.5],
            "close": [close + 0.1],
            "volume": [1000.0],
            "amount": [close * 1000.0],
        }
    )


def _development_bars() -> pd.DataFrame:
    rows = []
    for symbol in SYMBOLS:
        for market_date in ("2024-06-03", "2026-07-14"):
            rows.append(
                {
                    "symbol": symbol,
                    "date": market_date,
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.5,
                    "close": 10.1,
                    "volume": 1000.0,
                    "amount": 10100.0,
                }
            )
    return pd.DataFrame(rows)


def _write_plan(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "plan_id": "guard_v1_acquisition_test",
                "candidate": "liquidity_neutral_momentum_guard_price_volume",
                "development_data": {"end": "2026-07-14", "independent_holdout": False},
                "hypothesis": "The frozen guard survives a prospective holdout.",
                "required_data": ["reviewed source QA"],
                "required_tests": ["terminal holdout"],
                "stop_conditions": ["Stop on deterministic BLOCK."],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _write_config(path: Path, cache: Path) -> Path:
    payload = {
        "research": {
            "start": "2024-06-03",
            "end": "2026-07-14",
            "in_sample_end": "2025-06-30",
            "out_sample_start": "2025-07-01",
            "initial_cash": 1_000_000.0,
            "rebalance": "monthly",
            "allow_demo_data": False,
        },
        "data": {"source": "akshare", "cache_path": str(cache), "adjust": "qfq"},
        "universe": {
            "mode": "all_a",
            "index_code": "000906",
            "include_st": False,
            "min_history_days": 120,
        },
        "strategy": {"name": "multi_factor", "n_holdings": 30, "max_weight": 0.05},
        "risk": {"max_drawdown_stop": 0.2},
        "broker": {
            "commission_rate": 0.00025,
            "stamp_tax": 0.0005,
            "slippage_bps": 5,
            "price_limit_pct": 0.1,
            "lot_size": 100,
        },
        "output": {"results_dir": str(path.parent / "results")},
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _check_status(report, code: str) -> str:
    return next(item.status for item in report.checks if item.code == code)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
