from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import pandas as pd
import yaml

from quantify.data.storage import BarStorage
from quantify.research.prospective_trial_packet import (
    append_packet_preregistration,
    build_prospective_trial_packet,
    write_prospective_trial_packet,
)
from quantify.research.sealed_holdout_intake import (
    LEDGER_FILENAME,
    build_sealed_holdout_intake,
    retain_sealed_holdout_intake,
    verify_collection_ledger,
)
from quantify.research.trial_registry import append_result

REGISTRATION_TIME = datetime(2026, 7, 16, 0, 0, tzinfo=UTC)
AFTER_CLOSE = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)


def test_valid_daily_csv_is_retained_without_touching_execution_cache(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    daily = _write_daily_csv(tmp_path / "bars_20260717.csv")
    cache_hash_before = _sha256(paths["cache"])
    output = tmp_path / "quarantine"
    _set_intake_clock(monkeypatch, AFTER_CLOSE)

    prepared = _build(paths, daily, output)

    assert prepared.status == "PASS", prepared.blockers
    assert prepared.retention_allowed is True
    assert prepared.retained is False
    assert prepared.execution_cache_write_allowed is False
    assert prepared.holdout_analysis_allowed is False
    assert prepared.promotion_eligible is False
    assert not output.exists()

    committed = retain_sealed_holdout_intake(
        prepared,
        daily_bars_csv=daily,
        output_dir=output,
    )

    assert committed.status == "PASS"
    assert committed.retained is True
    assert committed.ledger_event is not None
    assert committed.ledger_event["evidence_role"] == "unreviewed_quarantine"
    assert committed.ledger_event["previous_hash"] == "0" * 64
    assert Path(committed.retained_path).read_bytes() == daily.read_bytes()
    assert _sha256(paths["cache"]) == cache_hash_before
    assert len(verify_collection_ledger(output / LEDGER_FILENAME)) == 1
    assert (output / "sealed_holdout_intake.json").is_file()
    assert len(list((output / "intake_reports").glob("*.json"))) == 1


def test_identical_market_date_replay_is_idempotent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    daily = _write_daily_csv(tmp_path / "bars.csv")
    output = tmp_path / "quarantine"
    _set_intake_clock(monkeypatch, AFTER_CLOSE)
    first = retain_sealed_holdout_intake(
        _build(paths, daily, output),
        daily_bars_csv=daily,
        output_dir=output,
    )
    ledger_before = (output / LEDGER_FILENAME).read_bytes()

    replay = _build(paths, daily, output)
    committed = retain_sealed_holdout_intake(
        replay,
        daily_bars_csv=daily,
        output_dir=output,
    )

    assert replay.status == "PASS"
    assert replay.idempotent is True
    assert committed.retained is True
    assert committed.ledger_event is None
    assert committed.existing_event == first.ledger_event
    assert (output / LEDGER_FILENAME).read_bytes() == ledger_before
    assert len(verify_collection_ledger(output / LEDGER_FILENAME)) == 1


def test_different_file_for_same_market_date_is_blocked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    first_csv = _write_daily_csv(tmp_path / "first.csv")
    changed_csv = _write_daily_csv(tmp_path / "changed.csv", close=10.8)
    output = tmp_path / "quarantine"
    _set_intake_clock(monkeypatch, AFTER_CLOSE)
    retain_sealed_holdout_intake(
        _build(paths, first_csv, output),
        daily_bars_csv=first_csv,
        output_dir=output,
    )
    ledger_before = (output / LEDGER_FILENAME).read_bytes()

    blocked = _build(paths, changed_csv, output)

    assert blocked.status == "BLOCK"
    assert blocked.retention_allowed is False
    assert _check_status(blocked, "COLLECTION_LEDGER_ADMISSION") == "BLOCK"
    assert (output / LEDGER_FILENAME).read_bytes() == ledger_before
    assert len(list((output / "sealed_inputs").glob("*.csv"))) == 1


def test_same_day_before_close_and_future_export_are_blocked_without_writes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    daily = _write_daily_csv(tmp_path / "bars.csv")
    output = tmp_path / "quarantine"
    _set_intake_clock(monkeypatch, datetime(2026, 7, 17, 6, 0, tzinfo=UTC))

    report = _build(
        paths,
        daily,
        output,
        source_exported_at="2026-07-17T16:00:00+08:00",
    )

    assert report.status == "BLOCK"
    assert _check_status(report, "SOURCE_EXPORT_TIMESTAMP") == "BLOCK"
    assert _check_status(report, "DAILY_BAR_FINALIZED") == "BLOCK"
    assert not output.exists()


def test_weekend_or_malformed_rows_fail_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    weekend = _write_daily_csv(tmp_path / "weekend.csv", market_date="2026-07-18")
    malformed = tmp_path / "malformed.csv"
    malformed.write_text(
        "symbol,date,open,high,low,close,volume,amount\n"
        "000001,2026-07-17,10,9,11,10,1000,10000\n",
        encoding="utf-8",
    )
    _set_intake_clock(monkeypatch, datetime(2026, 7, 20, 8, 0, tzinfo=UTC))

    weekend_report = _build(
        paths,
        weekend,
        tmp_path / "weekend-output",
        source_exported_at="2026-07-18T15:30:00+08:00",
    )
    malformed_report = _build(
        paths,
        malformed,
        tmp_path / "malformed-output",
        source_exported_at="2026-07-17T15:30:00+08:00",
    )

    assert weekend_report.status == "BLOCK"
    assert _check_status(weekend_report, "MARKET_DATE_WEEKDAY") == "BLOCK"
    assert malformed_report.status == "BLOCK"
    assert _check_status(malformed_report, "DAILY_CSV_CONTRACT") == "BLOCK"


def test_tampered_collection_ledger_blocks_future_intake(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    daily = _write_daily_csv(tmp_path / "bars.csv")
    next_daily = _write_daily_csv(tmp_path / "next.csv", market_date="2026-07-20")
    output = tmp_path / "quarantine"
    _set_intake_clock(monkeypatch, datetime(2026, 7, 20, 8, 0, tzinfo=UTC))
    retain_sealed_holdout_intake(
        _build(paths, daily, output),
        daily_bars_csv=daily,
        output_dir=output,
    )
    ledger = output / LEDGER_FILENAME
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    payload["row_count"] = 999
    ledger.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    report = _build(
        paths,
        next_daily,
        output,
        source_exported_at="2026-07-20T15:30:00+08:00",
    )

    assert report.status == "BLOCK"
    assert _check_status(report, "COLLECTION_LEDGER_ADMISSION") == "BLOCK"
    assert any("cannot be verified" in item.lower() for item in report.blockers)


def test_missing_prior_retained_bytes_block_future_append(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    daily = _write_daily_csv(tmp_path / "bars.csv")
    next_daily = _write_daily_csv(tmp_path / "next.csv", market_date="2026-07-20")
    output = tmp_path / "quarantine"
    _set_intake_clock(monkeypatch, datetime(2026, 7, 20, 8, 0, tzinfo=UTC))
    committed = retain_sealed_holdout_intake(
        _build(paths, daily, output),
        daily_bars_csv=daily,
        output_dir=output,
    )
    Path(committed.retained_path).unlink()

    report = _build(
        paths,
        next_daily,
        output,
        source_exported_at="2026-07-20T15:30:00+08:00",
    )

    assert report.status == "BLOCK"
    assert _check_status(report, "COLLECTION_LEDGER_ADMISSION") == "BLOCK"
    assert any("retained file is missing" in item.lower() for item in report.blockers)


def test_terminal_result_blocks_additional_quarantine_collection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    append_result(
        paths["registry"],
        trial_id="guard-v1-intake-test",
        result={"status": "BLOCK", "artifact_sha256": "a" * 64},
        created_at="2026-10-17T09:00:00+00:00",
    )
    daily = _write_daily_csv(tmp_path / "bars.csv")
    _set_intake_clock(monkeypatch, datetime(2026, 10, 17, 10, 0, tzinfo=UTC))

    report = _build(paths, daily, tmp_path / "quarantine")

    assert report.status == "BLOCK"
    assert _check_status(report, "TERMINAL_RESULT_ABSENT") == "BLOCK"
    assert report.retention_allowed is False


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
        trial_id="guard-v1-intake-test",
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


def _build(
    paths: dict[str, Path],
    daily: Path,
    output: Path,
    *,
    source_exported_at: str = "2026-07-17T15:30:00+08:00",
):
    return build_sealed_holdout_intake(
        packet_dir=paths["packet_dir"],
        trial_registry_path=paths["registry"],
        daily_bars_csv=daily,
        output_dir=output,
        source_vendor="licensed-test-vendor",
        source_reference="retained-export-20260717",
        source_exported_at=source_exported_at,
        price_adjustment="qfq",
    )


def _set_intake_clock(monkeypatch, value: datetime) -> None:
    monkeypatch.setattr(
        "quantify.research.sealed_holdout_intake._runtime_now",
        lambda: value,
    )


def _write_daily_csv(
    path: Path,
    *,
    market_date: str = "2026-07-17",
    close: float = 10.5,
) -> Path:
    path.write_text(
        "symbol,date,open,high,low,close,volume,amount\n"
        f"000001,{market_date},10,11,9,{close},1000,10500\n"
        f"600001,{market_date},20,21,19,20.5,2000,41000\n",
        encoding="utf-8",
    )
    return path


def _write_plan(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "plan_id": "guard_v1_intake_test",
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


def _check_status(report, code: str) -> str:
    return next(item.status for item in report.checks if item.code == code)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
