from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import pandas as pd
import yaml

from quantify.data.provenance import (
    LOGICAL_BAR_FINGERPRINT_ALGORITHM,
    PROSPECTIVE_PREFIX_FINGERPRINT_ALGORITHM_KEY,
    PROSPECTIVE_PREFIX_FINGERPRINT_END_KEY,
    PROSPECTIVE_PREFIX_FINGERPRINT_KEY,
)
from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.ops.run_manifest import build_run_manifest
from quantify.research.prospective_trial_packet import (
    append_packet_preregistration,
    build_prospective_trial_packet,
    build_prospective_trial_packet_verification,
    write_prospective_trial_packet,
)
from quantify.research.trial_registry import verify_registry
from quantify.research.trial_registry_review import _validate_manifest_fingerprints
from quantify.utils.config import Config


_FROZEN_NOW = datetime(2026, 7, 16, 0, 0, tzinfo=UTC)


def test_prefix_fingerprint_remains_stable_after_future_bars_are_appended(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "bars.db")
    storage.save_bars(_bars(["2026-07-14"]))
    prefix = storage.logical_bar_fingerprint(end="2026-07-14")

    storage.save_bars(_bars(["2026-07-17"], close=11.0))

    assert storage.logical_bar_fingerprint(end="2026-07-14") == prefix
    assert storage.logical_bar_fingerprint() != prefix


def test_packet_freezes_and_appends_before_holdout_without_upgrading_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "quantify.research.prospective_trial_packet._runtime_now", lambda: _FROZEN_NOW
    )
    cache = tmp_path / "development.db"
    BarStorage(cache).save_bars(_bars(["2024-06-03", "2026-07-14"]))
    plan = _write_plan(tmp_path / "plan.json")
    config = _write_config(tmp_path / "base.yaml", cache)

    packet = build_prospective_trial_packet(
        plan_path=plan,
        base_config_path=config,
        development_cache_path=cache,
        execution_cache_path=cache,
        trial_id="guard-v1-20260716",
        candidate="liquidity_neutral_momentum_guard_price_volume",
        train_start="2024-06-03",
        train_end="2025-06-30",
        selection_start="2025-07-01",
        selection_end="2026-07-14",
        test_start="2026-07-17",
        test_end="2026-10-16",
    )

    assert packet.status == "FROZEN_RESEARCH_ONLY"
    assert packet.registry_append_allowed is True
    assert packet.execution_allowed is False
    assert packet.development_data["promotion_status"] == "BLOCK"
    assert any("source QA" in item for item in packet.missing_evidence)
    assert packet.registration_payload is not None
    assert packet.registration_payload["prohibited_live_use"] is True

    output = write_prospective_trial_packet(packet, tmp_path / "packet")
    config_bytes = (output / "guard_v1_execution.yaml").read_bytes()
    assert hashlib.sha256(config_bytes).hexdigest() == packet.fingerprints["config_fingerprint"]
    assert yaml.safe_load(config_bytes)["prospective_trial"]["candidate"] == packet.candidate

    registry = tmp_path / "registry.jsonl"
    event = append_packet_preregistration(packet, registry)
    assert event.data_fingerprint == packet.fingerprints["data_fingerprint"]
    assert verify_registry(registry) == [event]


def test_packet_blocks_retroactive_registration(tmp_path: Path) -> None:
    cache = tmp_path / "development.db"
    BarStorage(cache).save_bars(_bars(["2026-07-14"]))
    packet = build_prospective_trial_packet(
        plan_path=_write_plan(tmp_path / "plan.json"),
        base_config_path=_write_config(tmp_path / "base.yaml", cache),
        development_cache_path=cache,
        execution_cache_path=cache,
        trial_id="guard-v1-retroactive",
        candidate="liquidity_neutral_momentum_guard_price_volume",
        train_start="2024-06-03",
        train_end="2025-06-30",
        selection_start="2025-07-01",
        selection_end="2026-07-14",
        test_start="2026-07-17",
        test_end="2026-10-16",
        created_at="2026-07-18T08:00:00+08:00",
    )

    assert packet.status == "BLOCK"
    assert packet.registry_append_allowed is False
    assert any("retroactive" in item for item in packet.blockers)


def test_run_manifest_records_verifiable_preregistered_prefix(tmp_path: Path) -> None:
    cache = tmp_path / "bars.db"
    storage = BarStorage(cache)
    storage.save_bars(_bars(["2026-07-14", "2026-07-17"], close=10.0))
    config_path = _write_config(tmp_path / "run.yaml", cache)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw["research"].update(
        {
            "start": "2026-07-14",
            "end": "2026-07-17",
            "in_sample_end": "2026-07-14",
            "out_sample_start": "2026-07-17",
        }
    )
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    cfg = Config(raw)
    manifest = build_run_manifest(
        DataProvider(storage),
        cfg,
        storage=storage,
        config_path=config_path,
    ).to_dict()

    version = manifest["data_version"]
    assert version[PROSPECTIVE_PREFIX_FINGERPRINT_KEY] == storage.logical_bar_fingerprint(
        end="2026-07-14"
    )
    assert version[PROSPECTIVE_PREFIX_FINGERPRINT_END_KEY] == "2026-07-14"
    assert version[PROSPECTIVE_PREFIX_FINGERPRINT_ALGORITHM_KEY] == (
        LOGICAL_BAR_FINGERPRINT_ALGORITHM
    )


def test_trial_review_accepts_prefix_only_with_matching_cutoff(tmp_path: Path) -> None:
    from quantify.research import prospective_trial_packet as packet_module

    original_clock = packet_module._runtime_now
    packet_module._runtime_now = lambda: _FROZEN_NOW
    cache = tmp_path / "development.db"
    BarStorage(cache).save_bars(_bars(["2026-07-14"]))
    try:
        packet = build_prospective_trial_packet(
            plan_path=_write_plan(tmp_path / "plan.json"),
            base_config_path=_write_config(tmp_path / "base.yaml", cache),
            development_cache_path=cache,
            execution_cache_path=cache,
            trial_id="guard-v1-prefix",
            candidate="liquidity_neutral_momentum_guard_price_volume",
            train_start="2024-06-03",
            train_end="2025-06-30",
            selection_start="2025-07-01",
            selection_end="2026-07-14",
            test_start="2026-07-17",
            test_end="2026-10-16",
        )
    finally:
        packet_module._runtime_now = original_clock
    registry = tmp_path / "registry.jsonl"
    event = append_packet_preregistration(packet, registry)
    manifest = {
        "config_sha256": event.config_fingerprint,
        "data_version": {
            PROSPECTIVE_PREFIX_FINGERPRINT_KEY: event.data_fingerprint,
            PROSPECTIVE_PREFIX_FINGERPRINT_END_KEY: "2026-07-14",
            PROSPECTIVE_PREFIX_FINGERPRINT_ALGORITHM_KEY: LOGICAL_BAR_FINGERPRINT_ALGORITHM,
        },
        "research_parameters": {
            "prospective_parameter_fingerprint": event.parameter_fingerprint,
        },
    }
    blockers: list[str] = []
    _validate_manifest_fingerprints(event, manifest, blockers)
    assert blockers == []

    manifest["data_version"][PROSPECTIVE_PREFIX_FINGERPRINT_END_KEY] = "2026-07-15"
    _validate_manifest_fingerprints(event, manifest, blockers)
    assert any("cutoff" in item for item in blockers)


def test_packet_verifier_detects_code_mutation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "quantify.research.prospective_trial_packet._runtime_now", lambda: _FROZEN_NOW
    )
    cache = tmp_path / "development.db"
    BarStorage(cache).save_bars(_bars(["2026-07-14"]))
    plan = _write_plan(tmp_path / "plan.json")
    code = tmp_path / "candidate_code.py"
    code.write_text("VALUE = 1\n", encoding="utf-8")
    packet = build_prospective_trial_packet(
        plan_path=plan,
        base_config_path=_write_config(tmp_path / "base.yaml", cache),
        development_cache_path=cache,
        execution_cache_path=cache,
        trial_id="guard-v1-verify",
        candidate="liquidity_neutral_momentum_guard_price_volume",
        train_start="2024-06-03",
        train_end="2025-06-30",
        selection_start="2025-07-01",
        selection_end="2026-07-14",
        test_start="2026-07-17",
        test_end="2026-10-16",
        code_paths=[code],
    )
    packet_dir = write_prospective_trial_packet(packet, tmp_path / "packet")
    (packet_dir / "protocol_plan.json").write_bytes(plan.read_bytes())
    registry = tmp_path / "registry.jsonl"
    append_packet_preregistration(packet, registry)

    passing = build_prospective_trial_packet_verification(
        packet_dir,
        registry,
    )
    assert passing.status == "PASS", passing.blockers
    assert passing.execution_allowed is False

    code.write_text("VALUE = 2\n", encoding="utf-8")
    blocked = build_prospective_trial_packet_verification(
        packet_dir,
        registry,
    )
    assert blocked.status == "BLOCK"
    assert any("Code SHA-256 mismatch" in item for item in blocked.blockers)


def _bars(dates: list[str], *, close: float = 10.0) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "000001",
                "date": item,
                "open": close,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 1000.0,
                "amount": close * 1000.0,
            }
            for item in dates
        ]
    )


def _write_plan(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "plan_id": "guard_v1",
                "candidate": "liquidity_neutral_momentum_guard_price_volume",
                "development_data": {"end": "2026-07-14", "independent_holdout": False},
                "hypothesis": "The frozen guard survives a fresh prospective holdout.",
                "required_data": ["reviewed source QA", "PIT CSI 800", "total return benchmark"],
                "required_tests": ["selection-safe walk-forward", "cost stress"],
                "stop_conditions": ["Stop on any deterministic evidence BLOCK."],
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
