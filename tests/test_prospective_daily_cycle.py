from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from examples.run_prospective_daily_cycle import main as cycle_main
from quantify.data.prospective_daily_acquisition import (
    build_prospective_daily_acquisition_preflight,
    run_prospective_daily_acquisition,
)
from quantify.data.prospective_acquisition_journal import (
    record_prospective_acquisition_attempt,
    verify_prospective_acquisition_attempts,
)
from quantify.data.storage import BarStorage
from quantify.ops.prospective_daily_cycle import (
    run_prospective_daily_cycle,
    write_prospective_daily_cycle,
)
from quantify.research.prospective_trial_packet import (
    append_packet_preregistration,
    build_prospective_trial_packet,
    write_prospective_trial_packet,
)
from quantify.research.sealed_holdout_intake import verify_collection_ledger

REGISTRATION_TIME = datetime(2026, 7, 16, 0, 0, tzinfo=UTC)
BEFORE_CLOSE = datetime(2026, 7, 16, 21, 0, tzinfo=UTC)
AFTER_CLOSE = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)


def test_cycle_before_close_is_offline_not_due(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    quarantine = tmp_path / "quarantine"
    cycle_output = tmp_path / "cycle"
    _set_clocks(monkeypatch, BEFORE_CLOSE)

    report = _cycle(paths, quarantine, cycle_output)
    output = write_prospective_daily_cycle(report, cycle_output)

    assert report.status == "NOT_DUE"
    assert report.target_date == ""
    assert report.execution_requested is False
    assert report.execution_performed is False
    assert report.network_access is False
    assert report.acquisition is None
    assert report.to_dict()["holdout_analysis_allowed"] is False
    assert report.to_dict()["broker_access"] is False
    assert not quarantine.exists()
    assert (output / "prospective_daily_cycle.json").is_file()
    assert (output / "collection_before" / "prospective_collection_status.json").is_file()


def test_cycle_after_close_prepares_action_without_network(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    quarantine = tmp_path / "quarantine"
    cycle_output = tmp_path / "cycle"
    _set_clocks(monkeypatch, AFTER_CLOSE)

    report = _cycle(paths, quarantine, cycle_output)
    output = write_prospective_daily_cycle(report, cycle_output)

    assert report.status == "ACTION_REQUIRED", report.blockers
    assert report.target_date == "2026-07-17"
    assert report.acquisition is not None
    assert report.acquisition.status == "READY"
    assert report.execution_performed is False
    assert report.network_access is False
    assert "--market-date 2026-07-17" in report.next_command
    assert not quarantine.exists()
    assert (output / "acquisition" / "prospective_daily_acquisition.json").is_file()


def test_explicit_cycle_collects_journals_and_seals_earliest_gap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    quarantine = tmp_path / "quarantine"
    cycle_output = tmp_path / "cycle"
    cache_hash_before = _sha256(paths["cache"])
    _set_clocks(monkeypatch, AFTER_CLOSE)

    report = _cycle(
        paths,
        quarantine,
        cycle_output,
        execute_acquisition=True,
        fetch_symbol=_successful_fetch,
    )
    write_prospective_daily_cycle(report, cycle_output)

    assert report.status == "COLLECTED", report.blockers
    assert report.execution_requested is True
    assert report.execution_performed is True
    assert report.network_access is True
    assert report.attempt_event is not None
    assert report.attempt_event["status"] == "PASS"
    assert report.intake is not None and report.intake.retained is True
    assert report.after_collection is not None
    assert report.after_collection.status == "WATCH"
    assert report.after_collection.unresolved_dates == ()
    assert len(verify_prospective_acquisition_attempts(quarantine)) == 1
    assert len(verify_collection_ledger(quarantine / "sealed_holdout_collection.jsonl")) == 1
    assert _sha256(paths["cache"]) == cache_hash_before


def test_blocked_attempt_requires_explicit_retry_authorization(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    quarantine = tmp_path / "quarantine"
    _set_clocks(monkeypatch, AFTER_CLOSE)

    blocked = _cycle(
        paths,
        quarantine,
        tmp_path / "cycle-blocked",
        execute_acquisition=True,
        fetch_symbol=_failed_fetch,
        max_attempts=1,
    )
    review = _cycle(
        paths,
        quarantine,
        tmp_path / "cycle-review",
        execute_acquisition=True,
        fetch_symbol=_successful_fetch,
    )
    retried = _cycle(
        paths,
        quarantine,
        tmp_path / "cycle-retry",
        execute_acquisition=True,
        retry_blocked_attempt=True,
        fetch_symbol=_successful_fetch,
    )

    assert blocked.status == "BLOCK"
    assert blocked.execution_performed is True
    assert blocked.network_access is True
    assert len(verify_prospective_acquisition_attempts(quarantine)) == 2
    assert review.status == "REVIEW_REQUIRED"
    assert review.execution_performed is False
    assert review.network_access is False
    assert retried.status == "COLLECTED", retried.blockers
    assert retried.retry_blocked_attempt_authorized is True
    assert retried.attempt_event is not None and retried.attempt_event["sequence"] == 2


def test_pass_attempt_without_handoff_never_refetches_automatically(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    quarantine = tmp_path / "quarantine"
    _set_clocks(monkeypatch, AFTER_CLOSE)
    preflight = build_prospective_daily_acquisition_preflight(
        packet_dir=paths["packet_dir"],
        trial_registry_path=paths["registry"],
        output_dir=quarantine,
        market_date="2026-07-17",
    )
    acquisition = run_prospective_daily_acquisition(
        preflight,
        output_dir=quarantine,
        fetch_symbol=_successful_fetch,
        retry_delay_seconds=0,
    )
    record_prospective_acquisition_attempt(acquisition, quarantine)

    report = _cycle(
        paths,
        quarantine,
        tmp_path / "cycle",
        execute_acquisition=True,
        retry_blocked_attempt=True,
        fetch_symbol=_failed_fetch,
    )

    assert report.status == "REVIEW_REQUIRED"
    assert report.execution_performed is False
    assert report.network_access is False
    assert len(verify_prospective_acquisition_attempts(quarantine)) == 1
    assert any("handoff" in item for item in report.blockers)


def test_tampered_journal_blocks_cycle_before_network(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    quarantine = tmp_path / "quarantine"
    _set_clocks(monkeypatch, AFTER_CLOSE)
    preflight = build_prospective_daily_acquisition_preflight(
        packet_dir=paths["packet_dir"],
        trial_registry_path=paths["registry"],
        output_dir=quarantine,
        market_date="2026-07-17",
    )
    acquisition = run_prospective_daily_acquisition(
        preflight,
        output_dir=quarantine,
        fetch_symbol=_failed_fetch,
        max_attempts=1,
        retry_delay_seconds=0,
    )
    event = record_prospective_acquisition_attempt(acquisition, quarantine)
    attempt_report = quarantine / event["report_relative_path"]
    attempt_report.write_bytes(attempt_report.read_bytes() + b"\n")

    report = _cycle(
        paths,
        quarantine,
        tmp_path / "cycle",
        execute_acquisition=True,
        retry_blocked_attempt=True,
        fetch_symbol=_successful_fetch,
    )

    assert report.status == "BLOCK"
    assert report.execution_performed is False
    assert report.network_access is False
    assert report.acquisition is None
    assert any("journal" in item.lower() for item in report.blockers)


def test_cycle_rejects_overlapping_outputs_and_cli_writes_offline_action(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    paths = _registered_trial(tmp_path, monkeypatch)
    quarantine = tmp_path / "quarantine"
    _set_clocks(monkeypatch, AFTER_CLOSE)

    with pytest.raises(ValueError, match="must be disjoint"):
        _cycle(paths, quarantine, quarantine)

    output = tmp_path / "cycle"
    exit_code = cycle_main(
        [
            "--packet-dir",
            str(paths["packet_dir"]),
            "--registry",
            str(paths["registry"]),
            "--quarantine-root",
            str(quarantine),
            "--output-dir",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Prospective daily cycle: ACTION_REQUIRED" in captured.out
    assert "Network access: False" in captured.out
    assert not quarantine.exists()
    assert (output / "prospective_daily_cycle.json").is_file()


def _cycle(
    paths: dict[str, Path],
    quarantine: Path,
    cycle_output: Path,
    **kwargs,
):
    return run_prospective_daily_cycle(
        packet_dir=paths["packet_dir"],
        trial_registry_path=paths["registry"],
        quarantine_root=quarantine,
        cycle_output_dir=cycle_output,
        retry_delay_seconds=0,
        **kwargs,
    )


def _set_clocks(monkeypatch, value: datetime) -> None:
    monkeypatch.setattr(
        "quantify.research.prospective_collection_status._runtime_now",
        lambda: value,
    )
    monkeypatch.setattr(
        "quantify.data.prospective_daily_acquisition._runtime_now",
        lambda: value,
    )
    monkeypatch.setattr(
        "quantify.research.sealed_holdout_intake._runtime_now",
        lambda: value,
    )
    monkeypatch.setattr(
        "quantify.ops.prospective_daily_cycle._runtime_now",
        lambda: value,
    )


def _successful_fetch(symbol: str, start: str, end: str):
    return _provider_frame(symbol, start), "eastmoney"


def _failed_fetch(symbol: str, start: str, end: str):
    raise ConnectionError("provider unavailable")


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
        trial_id="guard-v1-daily-cycle-test",
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


def _development_bars() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "000001",
                "date": market_date,
                "open": 10.0,
                "high": 10.5,
                "low": 9.5,
                "close": 10.1,
                "volume": 1000.0,
                "amount": 10100.0,
            }
            for market_date in ("2024-06-03", "2026-07-14")
        ]
    )


def _write_plan(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "plan_id": "guard_v1_daily_cycle_test",
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
