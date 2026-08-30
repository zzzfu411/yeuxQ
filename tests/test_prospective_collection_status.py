from __future__ import annotations

from datetime import UTC, datetime
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd
import yaml

from quantify.data.prospective_daily_acquisition import (
    build_prospective_daily_acquisition_preflight,
    run_prospective_daily_acquisition,
)
from quantify.data.prospective_acquisition_journal import (
    record_prospective_acquisition_attempt,
)
from quantify.data.storage import BarStorage
from quantify.research.prospective_collection_status import (
    build_prospective_collection_status,
    write_prospective_collection_status,
)
from quantify.research.prospective_trial_packet import (
    append_packet_preregistration,
    build_prospective_trial_packet,
    write_prospective_trial_packet,
)
from quantify.research.sealed_holdout_intake import (
    build_sealed_holdout_intake,
    retain_sealed_holdout_intake,
)
from quantify.research.trial_registry import append_result

REGISTRATION_TIME = datetime(2026, 7, 16, 0, 0, tzinfo=UTC)
FRIDAY_BEFORE_CLOSE = datetime(2026, 7, 16, 21, 0, tzinfo=UTC)
FRIDAY_AFTER_CLOSE = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
MONDAY_BEFORE_CLOSE = datetime(2026, 7, 19, 21, 0, tzinfo=UTC)
MONDAY_AFTER_CLOSE = datetime(2026, 7, 20, 8, 0, tzinfo=UTC)


def test_first_test_date_before_close_is_not_due(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    _set_status_clock(monkeypatch, FRIDAY_BEFORE_CLOSE)

    report = _status(paths, tmp_path / "quarantine")

    assert report.status == "NOT_DUE"
    assert report.schema_version == 2
    assert report.finalized_through == "2026-07-16"
    assert report.due_candidate_weekdays == ()
    assert report.unresolved_dates == ()
    assert report.next_candidate_date == "2026-07-17"
    assert "--market-date 2026-07-17" in report.next_command
    assert report.quarantine_coverage_current is True
    assert report.holdout_analysis_allowed is False


def test_missing_first_date_after_close_is_blocked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    _set_status_clock(monkeypatch, FRIDAY_AFTER_CLOSE)

    report = _status(paths, tmp_path / "quarantine")

    assert report.status == "BLOCK"
    assert report.due_candidate_weekdays == ("2026-07-17",)
    assert report.unresolved_dates == ("2026-07-17",)
    assert report.earliest_unresolved_date == "2026-07-17"
    assert _check_status(report, "DUE_WEEKDAY_CONTINUITY") == "BLOCK"
    assert "--market-date 2026-07-17" in report.next_command
    assert report.quarantine_coverage_current is False


def test_retained_first_date_is_watch_until_reviewed_calendar_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    quarantine = tmp_path / "quarantine"
    _retain_friday(paths, quarantine, tmp_path, monkeypatch)
    _set_status_clock(monkeypatch, FRIDAY_AFTER_CLOSE)

    report = _status(paths, quarantine)
    output = write_prospective_collection_status(report, tmp_path / "status")

    assert report.status == "WATCH"
    assert report.retained_dates == ("2026-07-17",)
    assert report.unresolved_dates == ()
    assert report.coverage_complete_through == "2026-07-17"
    assert report.calendar_evidence_status == "MISSING"
    assert _check_status(report, "REVIEWED_CALENDAR_EVIDENCE") == "WATCH"
    assert report.quarantine_coverage_current is True
    assert report.promotion_eligible is False
    assert (output / "prospective_collection_status.json").is_file()
    assert (output / "prospective_collection_timeline.csv").is_file()


def test_reviewed_weekday_closure_does_not_create_false_gap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    quarantine = tmp_path / "quarantine"
    _retain_friday(paths, quarantine, tmp_path, monkeypatch)
    calendar = _reviewed_calendar(tmp_path, monday_open=False)
    _set_status_clock(monkeypatch, MONDAY_AFTER_CLOSE)
    _set_calendar_clock(monkeypatch, MONDAY_AFTER_CLOSE)

    report = _status(
        paths,
        quarantine,
        calendar_csv=calendar["csv"],
        calendar_metadata=calendar["metadata"],
    )

    assert report.status == "PASS", report.blockers
    assert report.calendar_evidence_status == "PASS"
    assert report.calendar_model == "reviewed_exchange_calendar"
    assert report.due_candidate_weekdays == ("2026-07-17",)
    assert report.unresolved_dates == ()
    assert report.coverage_complete_through == "2026-07-17"
    assert _timeline_state(report, "2026-07-20") == "REVIEWED_MARKET_CLOSED"
    assert _check_status(report, "REVIEWED_CALENDAR_EVIDENCE") == "PASS"
    assert all("Acquire reviewed" not in action for action in report.next_actions)


def test_reviewed_open_session_requires_retained_collection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    quarantine = tmp_path / "quarantine"
    _retain_friday(paths, quarantine, tmp_path, monkeypatch)
    calendar = _reviewed_calendar(tmp_path, monday_open=True)
    _set_status_clock(monkeypatch, MONDAY_AFTER_CLOSE)
    _set_calendar_clock(monkeypatch, MONDAY_AFTER_CLOSE)

    report = _status(
        paths,
        quarantine,
        calendar_csv=calendar["csv"],
        calendar_metadata=calendar["metadata"],
    )

    assert report.status == "BLOCK"
    assert report.calendar_evidence_status == "PASS"
    assert report.due_candidate_weekdays == ("2026-07-17", "2026-07-20")
    assert report.unresolved_dates == ("2026-07-20",)
    assert report.earliest_unresolved_date == "2026-07-20"
    assert _timeline_state(report, "2026-07-20") == "DUE_UNRESOLVED"
    assert _check_status(report, "DUE_WEEKDAY_CONTINUITY") == "BLOCK"
    assert f'--calendar-csv "{calendar["csv"]}"' in report.next_command
    assert f'--calendar-metadata "{calendar["metadata"]}"' in report.next_command


def test_incomplete_calendar_input_pair_blocks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    calendar = _reviewed_calendar(tmp_path, monday_open=False)
    _set_status_clock(monkeypatch, FRIDAY_AFTER_CLOSE)

    report = _status(
        paths,
        tmp_path / "quarantine",
        calendar_csv=calendar["csv"],
    )

    assert report.status == "BLOCK"
    assert report.calendar_evidence_status == "BLOCK"
    assert report.calendar_preflight is None
    assert _check_status(report, "REVIEWED_CALENDAR_INPUT_PAIR") == "BLOCK"


def test_invalid_reviewed_calendar_blocks_continuity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    quarantine = tmp_path / "quarantine"
    _retain_friday(paths, quarantine, tmp_path, monkeypatch)
    calendar = _reviewed_calendar(tmp_path, monday_open=False)
    metadata = json.loads(calendar["metadata"].read_text(encoding="utf-8"))
    metadata["file_sha256"] = "0" * 64
    calendar["metadata"].write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    _set_status_clock(monkeypatch, MONDAY_AFTER_CLOSE)
    _set_calendar_clock(monkeypatch, MONDAY_AFTER_CLOSE)

    report = _status(
        paths,
        quarantine,
        calendar_csv=calendar["csv"],
        calendar_metadata=calendar["metadata"],
    )

    assert report.status == "BLOCK"
    assert report.calendar_evidence_status == "BLOCK"
    assert report.calendar_preflight is not None
    assert report.calendar_preflight.status == "BLOCK"
    assert _check_status(report, "REVIEWED_CALENDAR_EVIDENCE") == "BLOCK"


def test_monday_before_close_does_not_create_false_gap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    quarantine = tmp_path / "quarantine"
    _retain_friday(paths, quarantine, tmp_path, monkeypatch)
    _set_status_clock(monkeypatch, MONDAY_BEFORE_CLOSE)

    report = _status(paths, quarantine)

    assert report.status == "WATCH"
    assert report.finalized_through == "2026-07-19"
    assert report.due_candidate_weekdays == ("2026-07-17",)
    assert report.unresolved_dates == ()
    assert report.next_candidate_date == "2026-07-20"
    assert _timeline_state(report, "2026-07-20") == "FUTURE_CANDIDATE"


def test_monday_after_close_exposes_gap_and_refuses_silent_skip(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    quarantine = tmp_path / "quarantine"
    _retain_friday(paths, quarantine, tmp_path, monkeypatch)
    _set_status_clock(monkeypatch, MONDAY_AFTER_CLOSE)

    report = _status(paths, quarantine)

    assert report.status == "BLOCK"
    assert report.unresolved_dates == ("2026-07-20",)
    assert report.earliest_unresolved_date == "2026-07-20"
    assert _timeline_state(report, "2026-07-20") == "DUE_UNRESOLVED"
    assert "--market-date 2026-07-20" in report.next_command


def test_blocked_provider_attempt_is_visible_in_collection_timeline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    quarantine = tmp_path / "quarantine"
    event = _record_attempt(
        paths,
        quarantine,
        monkeypatch,
        market_date="2026-07-17",
        observed_at=FRIDAY_AFTER_CLOSE,
        provider_pass=False,
    )
    _set_status_clock(monkeypatch, FRIDAY_AFTER_CLOSE)

    report = _status(paths, quarantine)
    row = _timeline_row_for(report, "2026-07-17")

    assert report.status == "BLOCK"
    assert report.attempt_journal_status == "PASS"
    assert report.attempt_event_count == 1
    assert report.attempt_journal_tail_hash == event["event_hash"]
    assert report.latest_attempt == event
    assert row["attempt_count"] == 1
    assert row["latest_attempt_status"] == "BLOCK"
    assert row["latest_attempt_coverage"] == "0/1"
    assert any("Latest provider attempt" in action for action in report.next_actions)


def test_pass_provider_attempt_without_handoff_is_visible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    quarantine = tmp_path / "quarantine"
    _record_attempt(
        paths,
        quarantine,
        monkeypatch,
        market_date="2026-07-17",
        observed_at=FRIDAY_AFTER_CLOSE,
        provider_pass=True,
    )
    _set_status_clock(monkeypatch, FRIDAY_AFTER_CLOSE)

    report = _status(paths, quarantine)
    row = _timeline_row_for(report, "2026-07-17")

    assert report.status == "BLOCK"
    assert row["latest_attempt_status"] == "PASS"
    assert row["latest_attempt_coverage"] == "1/1"
    assert any("no sealed collection event" in action for action in report.next_actions)


def test_tampered_attempt_report_blocks_collection_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    quarantine = tmp_path / "quarantine"
    event = _record_attempt(
        paths,
        quarantine,
        monkeypatch,
        market_date="2026-07-17",
        observed_at=FRIDAY_AFTER_CLOSE,
        provider_pass=False,
    )
    attempt_report = quarantine / event["report_relative_path"]
    attempt_report.write_bytes(attempt_report.read_bytes() + b"\n")
    _set_status_clock(monkeypatch, FRIDAY_AFTER_CLOSE)

    report = _status(paths, quarantine)

    assert report.status == "BLOCK"
    assert report.attempt_journal_status == "BLOCK"
    assert report.attempt_event_count == 0
    assert _check_status(report, "ACQUISITION_ATTEMPT_JOURNAL") == "BLOCK"


def test_reviewed_closed_date_with_provider_attempt_blocks_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    quarantine = tmp_path / "quarantine"
    _retain_friday(paths, quarantine, tmp_path, monkeypatch)
    _record_attempt(
        paths,
        quarantine,
        monkeypatch,
        market_date="2026-07-20",
        observed_at=MONDAY_AFTER_CLOSE,
        provider_pass=False,
    )
    calendar = _reviewed_calendar(tmp_path, monday_open=False)
    _set_status_clock(monkeypatch, MONDAY_AFTER_CLOSE)
    _set_calendar_clock(monkeypatch, MONDAY_AFTER_CLOSE)

    report = _status(
        paths,
        quarantine,
        calendar_csv=calendar["csv"],
        calendar_metadata=calendar["metadata"],
    )

    assert report.status == "BLOCK"
    assert _check_status(report, "REVIEWED_CLOSED_DATES_HAVE_NO_ATTEMPTS") == "BLOCK"
    assert _timeline_row_for(report, "2026-07-20")["attempt_count"] == 1


def test_changed_retained_bytes_block_collection_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    quarantine = tmp_path / "quarantine"
    committed = _retain_friday(paths, quarantine, tmp_path, monkeypatch)
    Path(committed.retained_path).write_text("changed\n", encoding="utf-8")
    _set_status_clock(monkeypatch, FRIDAY_AFTER_CLOSE)

    report = _status(paths, quarantine)

    assert report.status == "BLOCK"
    assert _check_status(report, "QUARANTINE_LEDGER") == "BLOCK"
    assert report.retained_dates == ()


def test_terminal_result_blocks_collection_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    append_result(
        paths["registry"],
        trial_id="guard-v1-collection-status-test",
        result={"status": "BLOCK", "artifact_sha256": "a" * 64},
        created_at="2026-10-17T09:00:00+00:00",
    )
    _set_status_clock(monkeypatch, MONDAY_AFTER_CLOSE)

    report = _status(paths, tmp_path / "quarantine")

    assert report.status == "BLOCK"
    assert _check_status(report, "TERMINAL_RESULT_ABSENT") == "BLOCK"
    assert report.holdout_analysis_allowed is False


def _registered_trial(tmp_path: Path, monkeypatch) -> dict[str, Path]:
    monkeypatch.setattr(
        "quantify.research.prospective_trial_packet._runtime_now",
        lambda: REGISTRATION_TIME,
    )
    cache = tmp_path / "development.db"
    BarStorage(cache).save_bars(_bars(["2024-06-03", "2026-07-14"]))
    plan = _write_plan(tmp_path / "protocol_plan.json")
    config = _write_config(tmp_path / "base.yaml", cache)
    code = tmp_path / "frozen_candidate.py"
    code.write_text("VALUE = 1\n", encoding="utf-8")
    packet = build_prospective_trial_packet(
        plan_path=plan,
        base_config_path=config,
        development_cache_path=cache,
        execution_cache_path=cache,
        trial_id="guard-v1-collection-status-test",
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


def _retain_friday(paths: dict[str, Path], quarantine: Path, tmp_path: Path, monkeypatch):
    daily = tmp_path / "bars_20260717.csv"
    daily.write_text(
        "symbol,date,open,high,low,close,volume,amount\n"
        "000001,2026-07-17,10,11,9,10.5,1000,10500\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "quantify.research.sealed_holdout_intake._runtime_now",
        lambda: FRIDAY_AFTER_CLOSE,
    )
    prepared = build_sealed_holdout_intake(
        packet_dir=paths["packet_dir"],
        trial_registry_path=paths["registry"],
        daily_bars_csv=daily,
        output_dir=quarantine,
        source_vendor="licensed-test-vendor",
        source_reference="retained-export-20260717",
        source_exported_at="2026-07-17T15:30:00+08:00",
        price_adjustment="qfq",
    )
    return retain_sealed_holdout_intake(
        prepared,
        daily_bars_csv=daily,
        output_dir=quarantine,
    )


def _status(
    paths: dict[str, Path],
    quarantine: Path,
    *,
    calendar_csv: Path | None = None,
    calendar_metadata: Path | None = None,
):
    return build_prospective_collection_status(
        packet_dir=paths["packet_dir"],
        trial_registry_path=paths["registry"],
        quarantine_root=quarantine,
        calendar_csv=calendar_csv,
        calendar_metadata=calendar_metadata,
    )


def _set_status_clock(monkeypatch, value: datetime) -> None:
    monkeypatch.setattr(
        "quantify.research.prospective_collection_status._runtime_now",
        lambda: value,
    )


def _set_calendar_clock(monkeypatch, value: datetime) -> None:
    monkeypatch.setattr(
        "quantify.data.exchange_calendar_preflight._runtime_now",
        lambda: value,
    )


def _record_attempt(
    paths: dict[str, Path],
    quarantine: Path,
    monkeypatch,
    *,
    market_date: str,
    observed_at: datetime,
    provider_pass: bool,
) -> dict:
    monkeypatch.setattr(
        "quantify.data.prospective_daily_acquisition._runtime_now",
        lambda: observed_at,
    )
    preflight = build_prospective_daily_acquisition_preflight(
        packet_dir=paths["packet_dir"],
        trial_registry_path=paths["registry"],
        output_dir=quarantine,
        market_date=market_date,
        minimum_success_ratio=1.0,
    )

    def fetch(symbol: str, start: str, end: str):
        if not provider_pass:
            raise ConnectionError("provider unavailable")
        return _provider_frame(symbol, start), "eastmoney"

    acquisition = run_prospective_daily_acquisition(
        preflight,
        output_dir=quarantine,
        fetch_symbol=fetch,
        max_attempts=1,
        retry_delay_seconds=0,
    )
    return record_prospective_acquisition_attempt(acquisition, quarantine)


def _provider_frame(symbol: str, market_date: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": [symbol],
            "date": [market_date],
            "open": [10.0],
            "high": [10.5],
            "low": [9.5],
            "close": [10.1],
            "volume": [1000.0],
            "amount": [10100.0],
        }
    )


def _reviewed_calendar(
    root: Path,
    *,
    monday_open: bool,
) -> dict[str, Path]:
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
    csv_sha256 = hashlib.sha256(csv_path.read_bytes()).hexdigest()
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
                "source_exported_at": "2026-07-20T15:35:00+08:00",
                "reviewed_by": "independent-test-reviewer",
                "reviewed_at": "2026-07-20T15:45:00+08:00",
                "file_sha256": csv_sha256,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"csv": csv_path, "metadata": metadata_path}


def _timeline_state(report, date_text: str) -> str:
    return next(row["state"] for row in report.timeline if row["date"] == date_text)


def _timeline_row_for(report, date_text: str) -> dict:
    return next(row for row in report.timeline if row["date"] == date_text)


def _check_status(report, code: str) -> str:
    return next(item.status for item in report.checks if item.code == code)


def _bars(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "000001",
                "date": item,
                "open": 10.0,
                "high": 10.5,
                "low": 9.5,
                "close": 10.1,
                "volume": 1000.0,
                "amount": 10100.0,
            }
            for item in dates
        ]
    )


def _write_plan(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "plan_id": "guard_v1_collection_status_test",
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
