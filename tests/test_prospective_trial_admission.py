from __future__ import annotations

import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import pandas as pd
import yaml

from quantify.data.storage import BarStorage
from quantify.research.prospective_trial_admission import (
    build_prospective_trial_admission,
    write_prospective_trial_admission,
)
from quantify.research.prospective_trial_packet import (
    append_packet_preregistration,
    build_prospective_trial_packet,
    write_prospective_trial_packet,
)
from quantify.research.trial_registry import append_result

REGISTRATION_TIME = datetime(2026, 7, 16, 0, 0, tzinfo=UTC)
# UTC is still July 16 while the A-share market date is already July 17.
SEALED_TIME = datetime(2026, 7, 16, 20, 0, tzinfo=UTC)
POST_HOLDOUT_TIME = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def test_holdout_remains_sealed_even_when_collection_prerequisites_pass(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fixture = _registered_trial(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "quantify.research.prospective_trial_admission._runtime_now",
        lambda: SEALED_TIME,
    )

    report = _build_admission(fixture)

    assert report.status == "BLOCK"
    assert report.phase == "HOLDOUT_SEALED"
    assert report.evaluated_market_date == "2026-07-17"
    assert report.market_timezone == "Asia/Shanghai"
    assert report.collection_ready is True
    assert report.terminal_analysis_allowed is False
    assert report.paper_trading_allowed is False
    assert report.live_trading_allowed is False
    assert _check_status(report, "HOLDOUT_TIME_SEAL") == "BLOCK"
    assert _check_status(report, "MARKET_EVIDENCE_NOT_FUTURE_DATED") == "BLOCK"
    assert any("sealed through 2026-10-16" in item for item in report.blockers)


def test_terminal_analysis_passes_only_after_all_dynamic_evidence_verifies(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fixture = _registered_trial(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "quantify.research.prospective_trial_admission._runtime_now",
        lambda: POST_HOLDOUT_TIME,
    )

    report = _build_admission(fixture)
    output = write_prospective_trial_admission(report, tmp_path / "admission")

    assert report.status == "PASS", report.blockers
    assert report.sufficient is True
    assert report.phase == "POST_HOLDOUT_ADMISSION"
    assert report.collection_ready is True
    assert report.terminal_analysis_allowed is True
    assert report.packet_verification.execution_allowed is False
    assert all(item.status == "PASS" for item in report.checks)
    assert (output / "prospective_trial_admission.json").is_file()
    assert (output / "prospective_trial_packet_verification.json").is_file()
    assert (output / "promotion_metadata_check.json").is_file()
    assert (output / "market_evidence_preflight.json").is_file()
    markdown = (output / "prospective_trial_admission.md").read_text(encoding="utf-8")
    assert "Terminal holdout analysis allowed: `True`" in markdown
    assert "Live trading allowed: `False`" in markdown


def test_existing_terminal_result_blocks_repeat_analysis(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fixture = _registered_trial(tmp_path, monkeypatch)
    append_result(
        fixture["registry"],
        trial_id="guard-v1-test",
        result={"status": "BLOCK", "artifact_sha256": "a" * 64},
        created_at="2026-10-17T09:00:00+00:00",
    )
    monkeypatch.setattr(
        "quantify.research.prospective_trial_admission._runtime_now",
        lambda: POST_HOLDOUT_TIME,
    )

    report = _build_admission(fixture)

    assert report.status == "BLOCK"
    assert report.phase == "TERMINAL_RESULT_RECORDED"
    assert report.collection_ready is False
    assert report.terminal_analysis_allowed is False
    assert report.registry_state["matching_results"] == 1
    assert _check_status(report, "TERMINAL_RESULT_ABSENT") == "BLOCK"
    assert any("Do not rerun" in item for item in report.next_actions)


def test_source_route_mismatch_and_missing_market_files_fail_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fixture = _registered_trial(tmp_path, monkeypatch)
    BarStorage(fixture["cache"]).save_metadata({"data_source": "local_csv"})
    fixture["benchmark_csv"].unlink()
    monkeypatch.setattr(
        "quantify.research.prospective_trial_admission._runtime_now",
        lambda: POST_HOLDOUT_TIME,
    )

    report = _build_admission(fixture)

    assert report.status == "BLOCK"
    assert report.collection_ready is False
    assert _check_status(report, "CONFIGURED_SOURCE_IDENTITY") == "BLOCK"
    assert _check_status(report, "MARKET_EVIDENCE") == "BLOCK"
    assert report.market_evidence.status == "BLOCK"
    assert report.terminal_analysis_allowed is False


def _registered_trial(tmp_path: Path, monkeypatch) -> dict[str, Path]:
    monkeypatch.setattr(
        "quantify.research.prospective_trial_packet._runtime_now",
        lambda: REGISTRATION_TIME,
    )
    development_cache = tmp_path / "development.db"
    cache = tmp_path / "execution.db"
    qa_metadata = _source_qa_metadata(tmp_path)
    common_import = {
        "source_type": "akshare_reviewed_export",
        "source_reference": "retained-provider-export",
        "cache_metadata": {"data_source": "akshare", **qa_metadata},
        "batch_id": "development-prefix",
        "imported_at_utc": "2026-07-15T12:00:00+00:00",
    }
    BarStorage(development_cache).save_bars_with_lineage(
        _bars(["2024-06-03", "2026-07-14"]),
        **common_import,
    )
    storage = BarStorage(cache)
    storage.save_bars_with_lineage(
        _bars(["2024-06-03", "2026-07-14"]),
        **common_import,
    )
    plan = _write_plan(tmp_path / "protocol_plan.json")
    config = _write_config(tmp_path / "base.yaml", cache)
    code = tmp_path / "frozen_candidate.py"
    code.write_text("VALUE = 1\n", encoding="utf-8")
    packet = build_prospective_trial_packet(
        plan_path=plan,
        base_config_path=config,
        development_cache_path=development_cache,
        execution_cache_path=cache,
        trial_id="guard-v1-test",
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

    storage.save_bars_with_lineage(
        _bars(["2026-07-17", "2026-10-16"], close=11.0),
        source_type="akshare_reviewed_export",
        source_reference="retained-provider-export",
        batch_id="prospective-append",
        imported_at_utc="2026-10-16T12:00:00+00:00",
    )
    market = _write_market_evidence(tmp_path / "market")
    return {
        "packet_dir": packet_dir,
        "registry": registry,
        "cache": cache,
        **market,
    }


def _build_admission(paths: dict[str, Path]):
    return build_prospective_trial_admission(
        packet_dir=paths["packet_dir"],
        registry_path=paths["registry"],
        benchmark_csv=paths["benchmark_csv"],
        benchmark_metadata=paths["benchmark_metadata"],
        membership_csv=paths["membership_csv"],
        membership_metadata=paths["membership_metadata"],
        minimum_members_per_snapshot=2,
    )


def _source_qa_metadata(root: Path) -> dict[str, str]:
    qa = root / "source_qa"
    qa.mkdir()
    checklist = qa / "data_source_qa.json"
    answers = qa / "data_source_qa_answers.json"
    manifest = qa / "source_qa_evidence_manifest.json"
    checklist.write_text('{"checklist":[{"id":"source_identity"}]}', encoding="utf-8")
    answers.write_text('{"answers":{"source_identity":"yes"}}', encoding="utf-8")
    manifest.write_text('{"files":[{"name":"reviewed-export"}]}', encoding="utf-8")
    return {
        "data_source_qa_status": "PASS",
        "data_source_qa_checklist_path": str(checklist),
        "data_source_qa_checklist_sha256": _sha256(checklist),
        "data_source_qa_answers_path": str(answers),
        "data_source_qa_answers_sha256": _sha256(answers),
        "data_source_qa_evidence_manifest_path": str(manifest),
        "data_source_qa_evidence_manifest_sha256": _sha256(manifest),
        "data_source_qa_require_evidence_manifest": "true",
    }


def _write_market_evidence(root: Path) -> dict[str, Path]:
    root.mkdir()
    benchmark_csv = root / "csi800_total_return.csv"
    benchmark_metadata = root / "csi800_total_return.metadata.json"
    membership_csv = root / "csi800_pit_membership.csv"
    membership_metadata = root / "csi800_pit_membership.metadata.json"
    _write_csv(
        benchmark_csv,
        [
            {"date": "2024-06-03", "value": "1000"},
            {"date": "2025-06-30", "value": "1050"},
            {"date": "2026-10-16", "value": "1100"},
        ],
    )
    membership_rows = []
    for effective_date, symbols in (
        ("2024-06-03", ("000001", "600001")),
        ("2025-07-01", ("000001", "600002")),
        ("2026-10-16", ("000001", "600003")),
    ):
        membership_rows.extend(
            {
                "index_code": "000906",
                "effective_date": effective_date,
                "symbol": symbol,
            }
            for symbol in symbols
        )
    _write_csv(membership_csv, membership_rows)
    provenance = {
        "coverage_start_date": "2024-06-03",
        "coverage_end_date": "2026-10-16",
        "source_vendor": "licensed-test-vendor",
        "source_exported_at": "2026-10-16T18:00:00+08:00",
        "reviewed_by": "independent-test-reviewer",
        "reviewed_at": "2026-10-16T19:00:00+08:00",
    }
    _write_json(
        benchmark_metadata,
        {
            "artifact_type": "reviewed_benchmark_series",
            "schema_version": 1,
            "symbol": "000906.SH",
            "name": "CSI 800 Total Return",
            "total_return": True,
            "series_kind": "equity",
            **provenance,
            "file_sha256": _sha256(benchmark_csv),
        },
    )
    _write_json(
        membership_metadata,
        {
            "artifact_type": "reviewed_pit_universe_membership",
            "schema_version": 1,
            "index_code": "000906",
            "point_in_time": True,
            "snapshot_mode": "point_in_time_history",
            "effective_date_column": "effective_date",
            "symbol_column": "symbol",
            "index_code_column": "index_code",
            "source_dataset": "CSI 800 historical constituents",
            **provenance,
            "file_sha256": _sha256(membership_csv),
        },
    )
    return {
        "benchmark_csv": benchmark_csv,
        "benchmark_metadata": benchmark_metadata,
        "membership_csv": membership_csv,
        "membership_metadata": membership_metadata,
    }


def _write_plan(path: Path) -> Path:
    _write_json(
        path,
        {
            "plan_id": "guard_v1_test",
            "candidate": "liquidity_neutral_momentum_guard_price_volume",
            "development_data": {"end": "2026-07-14", "independent_holdout": False},
            "hypothesis": "The frozen guard survives a fresh prospective holdout.",
            "required_data": ["reviewed source QA", "PIT CSI 800"],
            "required_tests": ["terminal holdout"],
            "stop_conditions": ["Stop on deterministic BLOCK."],
        },
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


def _check_status(report, code: str) -> str:
    return next(item.status for item in report.checks if item.code == code)


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
