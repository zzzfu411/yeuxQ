from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

from quantify.research.candidate_experiment_queue import build_candidate_experiment_queue
from quantify.research.candidate_experiment_readiness import (
    build_candidate_experiment_readiness,
    build_candidate_experiment_readiness_from_report,
    write_candidate_experiment_readiness,
)
from quantify.utils.config import Config


def test_candidate_experiment_readiness_blocks_when_data_gates_block(tmp_path: Path) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    readiness = build_candidate_experiment_readiness(
        queue,
        stage_statuses={
            "candidate_experiment_queue": "PASS",
            "offline_data_package": "BLOCK",
            "source_qa_preflight": "BLOCK",
            "data_source_qa_review": "BLOCK",
            "offline_data_intake": "BLOCK",
        },
        stage_messages={
            "offline_data_package": "csv_template_rows: generated template sample rows remain.",
            "source_qa_preflight": "data_source_qa_answers.json: Source QA answers are missing or empty.",
            "data_source_qa_review": "SOURCE_QA_ANSWERS_MISSING",
            "offline_data_intake": "Stopped at source_qa.",
        },
        as_of="2026-06-08",
    )
    out = write_candidate_experiment_readiness(readiness, tmp_path / "out")

    payload = json.loads((out / "candidate_experiment_readiness.json").read_text(encoding="utf-8"))
    markdown = (out / "candidate_experiment_readiness.md").read_text(encoding="utf-8")
    with (out / "candidate_experiment_readiness_matrix.csv").open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        matrix = list(reader)

    assert payload["decision"] == "BLOCK"
    assert payload["runnable_count"] == 0
    assert payload["blocked_count"] == 18
    assert reader.fieldnames == [
        "priority",
        "candidate",
        "data_dependency",
        "evidence_scope",
        "evidence_path",
        "evidence_path_status",
        "status",
        "first_blocker",
        "blocker_count",
        "warning_count",
        "next_command",
        "source_provenance",
        "market_context_source",
        "market_context_status",
        "market_context_label",
        "intended_regimes",
        "market_regime_fit_status",
        "market_regime_fit",
    ]
    assert all(item["status"] == "BLOCKED" for item in payload["items"])
    assert any("source_qa_preflight=BLOCK" in blocker for blocker in payload["blockers"])
    assert any("data_source_qa_review=BLOCK" in blocker for blocker in payload["blockers"])
    assert "Do not run candidate research experiments while readiness is BLOCK." in markdown
    assert matrix[0]["candidate"] == "price_volume_defensive"
    assert matrix[0]["status"] == "BLOCKED"
    assert matrix[0]["evidence_scope"] == "OHLCV_ONLY"
    assert "source_qa_preflight=BLOCK" in matrix[0]["first_blocker"]


def test_candidate_experiment_readiness_blocks_when_source_qa_preflight_blocks(tmp_path: Path) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    readiness = build_candidate_experiment_readiness(
        queue,
        stage_statuses={
            "candidate_experiment_queue": "PASS",
            "offline_data_package": "PASS",
            "source_qa_preflight": "BLOCK",
            "data_source_qa_review": "PASS",
            "offline_data_intake": "PASS",
        },
        stage_messages={
            "source_qa_preflight": "data_source_qa_answers.json: Source QA answers are missing or empty.",
        },
        as_of="2026-06-08",
    )

    assert readiness.decision == "BLOCK"
    assert readiness.runnable_count == 0
    assert readiness.blocked_count == 18
    assert all(item.status == "BLOCKED" for item in readiness.items)
    assert any("source_qa_preflight=BLOCK" in blocker for blocker in readiness.blockers)
    assert any("source QA preflight" in action for action in readiness.next_actions)


def test_candidate_experiment_readiness_passes_when_required_stages_pass(tmp_path: Path) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    readiness = build_candidate_experiment_readiness(
        queue,
        stage_statuses={
            "candidate_experiment_queue": "PASS",
            "offline_data_package": "PASS",
            "source_qa_preflight": "PASS",
            "data_source_qa_review": "PASS",
            "offline_data_intake": "PASS",
        },
        as_of="2026-06-08",
    )

    assert readiness.decision == "PASS"
    assert readiness.runnable_count == 18
    assert readiness.blocked_count == 0
    assert readiness.scope_summary["OHLCV_ONLY"]["total"] == 13
    assert readiness.scope_summary["OHLCV_ONLY"]["ready"] == 13
    assert readiness.scope_summary["OHLCV_ONLY"]["first_ready_candidate"] == "price_volume_defensive"
    assert readiness.scope_summary["PIT_FUNDAMENTAL_REQUIRED"]["total"] == 5
    assert readiness.scope_summary["PIT_FUNDAMENTAL_REQUIRED"]["ready"] == 5
    assert readiness.items[0].candidate == "price_volume_defensive"
    assert readiness.items[0].data_dependency == "ohlcv_only"
    assert readiness.items[0].evidence_path == "ohlcv_minimum_path"
    assert readiness.items[0].next_command.startswith("python examples/run_candidate_experiment_evidence.py")
    first_experiment = queue.experiments[0]
    assert any(
        command.startswith("python examples/run_candidate_walk_forward.py")
        for command in first_experiment.command_sequence
    )


def test_candidate_experiment_readiness_blocks_missing_market_context_from_report(
    tmp_path: Path,
) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    (tmp_path / "candidate_experiment_queue.json").write_text(
        json.dumps(queue.to_dict(), ensure_ascii=False),
        encoding="utf-8",
    )
    _write_pipeline_stages(tmp_path, status="PASS")
    _write_handoff_paths(tmp_path, ohlcv_status="PASS", pit_status="PASS")
    _write_offline_package(tmp_path)

    readiness = build_candidate_experiment_readiness_from_report(tmp_path, as_of="2026-06-08")
    out = write_candidate_experiment_readiness(readiness, tmp_path)
    matrix = list(csv.DictReader((out / "candidate_experiment_readiness_matrix.csv").open(encoding="utf-8")))

    assert readiness.decision == "BLOCK"
    assert readiness.runnable_count == 0
    assert all(item.market_context_source == "missing" for item in readiness.items)
    assert all(item.market_context_status == "BLOCK" for item in readiness.items)
    assert any("market_context=MISSING" in blocker for blocker in readiness.blockers)
    assert any("market_regime.json" in action for action in readiness.next_actions)
    assert any("market_context_snapshot.json" in action for action in readiness.next_actions)
    assert matrix[0]["market_context_source"] == "missing"
    assert matrix[0]["market_context_status"] == "BLOCK"


def test_candidate_experiment_readiness_watches_with_market_context_snapshot(
    tmp_path: Path,
) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    (tmp_path / "candidate_experiment_queue.json").write_text(
        json.dumps(queue.to_dict(), ensure_ascii=False),
        encoding="utf-8",
    )
    _write_pipeline_stages(tmp_path, status="PASS")
    _write_handoff_paths(tmp_path, ohlcv_status="PASS", pit_status="BLOCK")
    _write_offline_package(tmp_path)
    _write_json(
        tmp_path / "market_context_snapshot.json",
        {
            "artifact_type": "market_context_snapshot",
            "status": "PASS",
            "label": "risk_on",
            "as_of": "2026-06-08",
            "source": "unit-test reviewed index export",
            "reviewed_by": "tester",
            "reviewed_at": "2026-06-08",
            "index_metrics": [
                {
                    "name": "CSI300",
                    "return_20d": 0.01,
                    "return_60d": 0.02,
                    "return_120d": 0.03,
                    "max_drawdown": 0.05,
                    "annualized_volatility": 0.18,
                }
            ],
            "can_replace_market_regime": False,
            "can_approve_strategy": False,
            "can_generate_broker_orders": False,
        },
    )

    readiness = build_candidate_experiment_readiness_from_report(tmp_path, as_of="2026-06-08")
    items = {item.candidate: item for item in readiness.items}

    assert readiness.decision == "WATCH"
    assert readiness.runnable_count == 13
    assert items["price_volume_defensive"].status == "READY"
    assert items["low_turnover_price_volume"].status == "READY"
    assert items["low_turnover_low_concentration_price_volume"].status == "READY"
    assert items["trend_filtered_price_volume"].status == "READY"
    assert items["trend_filtered_quarterly_price_volume"].status == "READY"
    assert items["trend_filtered_quarterly_low_concentration_price_volume"].status == "READY"
    assert items["defensive_scaled_quarterly_price_volume"].status == "READY"
    assert items["stable_universe_slow_signal_price_volume"].status == "READY"
    assert items["long_momentum_liquidity_monthly_price_volume"].status == "READY"
    assert items["liquidity_neutral_momentum_guard_price_volume"].status == "READY"
    assert items["defensive_cash_guard_price_volume"].status == "READY"
    assert items["risk_off_cash_stop_price_volume"].status == "READY"
    assert items["regime_pause_price_volume"].status == "READY"
    assert items["price_volume_defensive"].market_context_source == "market_context_snapshot"
    assert items["price_volume_defensive"].market_context_status == "WATCH"
    assert items["price_volume_defensive"].market_context_label == "risk_on"
    assert items["price_volume_defensive"].market_regime_fit_status == "WATCH"
    assert items["price_volume_defensive"].market_regime_fit == "opportunistic_only"
    assert items["trend_filtered_price_volume"].market_regime_fit_status == "WATCH"
    assert items["trend_filtered_price_volume"].market_regime_fit == "opportunistic_only"
    assert any("Only market_context_snapshot" in item for item in readiness.watch_items)


def test_candidate_experiment_readiness_blocks_incomplete_market_context_snapshot(
    tmp_path: Path,
) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    (tmp_path / "candidate_experiment_queue.json").write_text(
        json.dumps(queue.to_dict(), ensure_ascii=False),
        encoding="utf-8",
    )
    _write_pipeline_stages(tmp_path, status="PASS")
    _write_handoff_paths(tmp_path, ohlcv_status="PASS", pit_status="PASS")
    _write_offline_package(tmp_path)
    _write_json(
        tmp_path / "market_context_snapshot.json",
        {
            "artifact_type": "market_context_snapshot",
            "status": "PASS",
            "label": "risk_on",
            "can_replace_market_regime": False,
        },
    )

    readiness = build_candidate_experiment_readiness_from_report(tmp_path, as_of="2026-06-08")

    assert readiness.decision == "BLOCK"
    assert readiness.runnable_count == 0
    assert any("reviewed evidence field" in blocker for blocker in readiness.blockers)


def test_candidate_experiment_readiness_passes_with_cache_market_regime(
    tmp_path: Path,
) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    (tmp_path / "candidate_experiment_queue.json").write_text(
        json.dumps(queue.to_dict(), ensure_ascii=False),
        encoding="utf-8",
    )
    _write_pipeline_stages(tmp_path, status="PASS")
    _write_handoff_paths(tmp_path, ohlcv_status="PASS", pit_status="PASS")
    _write_offline_package(tmp_path)
    _write_json(
        tmp_path / "market_regime.json",
        {"status": "PASS", "label": "neutral", "as_of": "2026-06-08"},
    )

    readiness = build_candidate_experiment_readiness_from_report(tmp_path, as_of="2026-06-08")

    assert readiness.decision == "PASS"
    assert readiness.runnable_count == 18
    assert all(item.market_context_source == "market_regime" for item in readiness.items)
    assert all(item.market_context_status == "PASS" for item in readiness.items)
    assert all(item.market_context_label == "neutral" for item in readiness.items)
    assert all(item.market_regime_fit_status in {"PASS", "WATCH"} for item in readiness.items)


def test_candidate_experiment_readiness_blocks_upstream_hard_blocking_stage(
    tmp_path: Path,
) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    readiness = build_candidate_experiment_readiness(
        queue,
        stage_statuses={
            "candidate_experiment_queue": "PASS",
            "source_qa_preflight": "PASS",
            "data_source_qa_review": "PASS",
            "offline_data_package": "PASS",
            "offline_data_intake": "PASS",
            "data_source_selection": "BLOCK",
        },
        stage_messages={
            "data_source_selection": "Choose exactly one local data input.",
        },
        as_of="2026-06-08",
    )

    assert readiness.decision == "BLOCK"
    assert readiness.runnable_count == 0
    assert all(item.status == "BLOCKED" for item in readiness.items)
    assert any("data_source_selection=BLOCK" in blocker for blocker in readiness.blockers)


def test_candidate_experiment_readiness_allows_ohlcv_only_when_pit_path_blocks(
    tmp_path: Path,
) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    readiness = build_candidate_experiment_readiness(
        queue,
        stage_statuses={
            "candidate_experiment_queue": "PASS",
            "offline_data_package": "WATCH",
            "source_qa_preflight": "PASS",
            "data_source_qa_review": "PASS",
            "offline_data_intake": "WATCH",
        },
        stage_messages={
            "offline_data_package": "Recommended CSV files are missing.",
            "offline_data_intake": "CSV validation has WATCH evidence.",
        },
        handoff_payload={
            "evidence_paths": [
                {
                    "name": "ohlcv_minimum_path",
                    "status": "PASS",
                    "blocked_by": [],
                    "required_evidence": [
                        "Audited OHLCV bars and source QA evidence.",
                        "Explicit OHLCV-only scope note.",
                    ],
                    "next_action": "Run guarded offline intake.",
                },
                {
                    "name": "pit_fundamental_candidate_path",
                    "status": "BLOCK",
                    "blocked_by": ["fundamentals.csv is missing for valuation and quality candidates."],
                    "required_evidence": [
                        "fundamentals.csv contains point-in-time pe_ttm and roe coverage.",
                        "Candidate data-dependency review is PASS.",
                    ],
                    "next_action": "Keep fundamental-dependent candidates downgraded.",
                },
            ]
        },
        source_metadata_summary=_source_summary(),
        as_of="2026-06-08",
    )

    items = {item.candidate: item for item in readiness.items}
    assert readiness.decision == "WATCH"
    assert readiness.runnable_count == 13
    assert readiness.blocked_count == 5
    assert readiness.scope_summary["OHLCV_ONLY"]["total"] == 13
    assert readiness.scope_summary["OHLCV_ONLY"]["ready"] == 13
    assert readiness.scope_summary["OHLCV_ONLY"]["first_ready_candidate"] == "price_volume_defensive"
    assert "PIT claims remain prohibited" in readiness.scope_summary["OHLCV_ONLY"]["note"]
    assert readiness.scope_summary["PIT_FUNDAMENTAL_REQUIRED"]["total"] == 5
    assert readiness.scope_summary["PIT_FUNDAMENTAL_REQUIRED"]["blocked"] == 5
    assert "core_multifactor" in readiness.scope_summary["PIT_FUNDAMENTAL_REQUIRED"]["blocked_candidates"]
    assert "fundamentals provenance" in readiness.scope_summary["PIT_FUNDAMENTAL_REQUIRED"]["note"]
    assert items["price_volume_defensive"].status == "READY"
    assert items["price_volume_defensive"].evidence_scope == "OHLCV_ONLY"
    assert items["price_volume_defensive"].evidence_path_status == "PASS"
    assert items["low_turnover_price_volume"].status == "READY"
    assert items["low_turnover_price_volume"].evidence_scope == "OHLCV_ONLY"
    assert items["low_turnover_price_volume"].evidence_path_status == "PASS"
    assert items["low_turnover_low_concentration_price_volume"].status == "READY"
    assert items["low_turnover_low_concentration_price_volume"].evidence_scope == "OHLCV_ONLY"
    assert items["low_turnover_low_concentration_price_volume"].evidence_path_status == "PASS"
    assert items["trend_filtered_price_volume"].status == "READY"
    assert items["trend_filtered_price_volume"].evidence_scope == "OHLCV_ONLY"
    assert items["trend_filtered_price_volume"].evidence_path_status == "PASS"
    assert items["trend_filtered_quarterly_price_volume"].status == "READY"
    assert items["trend_filtered_quarterly_price_volume"].evidence_scope == "OHLCV_ONLY"
    assert items["trend_filtered_quarterly_price_volume"].evidence_path_status == "PASS"
    assert items["trend_filtered_quarterly_low_concentration_price_volume"].status == "READY"
    assert (
        items["trend_filtered_quarterly_low_concentration_price_volume"].evidence_scope
        == "OHLCV_ONLY"
    )
    assert (
        items["trend_filtered_quarterly_low_concentration_price_volume"].evidence_path_status
        == "PASS"
    )
    assert items["defensive_scaled_quarterly_price_volume"].status == "READY"
    assert items["defensive_scaled_quarterly_price_volume"].evidence_scope == "OHLCV_ONLY"
    assert items["defensive_scaled_quarterly_price_volume"].evidence_path_status == "PASS"
    assert items["stable_universe_slow_signal_price_volume"].status == "READY"
    assert items["stable_universe_slow_signal_price_volume"].evidence_scope == "OHLCV_ONLY"
    assert items["stable_universe_slow_signal_price_volume"].evidence_path_status == "PASS"
    assert items["long_momentum_liquidity_monthly_price_volume"].status == "READY"
    assert items["long_momentum_liquidity_monthly_price_volume"].evidence_scope == "OHLCV_ONLY"
    assert items["long_momentum_liquidity_monthly_price_volume"].evidence_path_status == "PASS"
    assert items["liquidity_neutral_momentum_guard_price_volume"].status == "READY"
    assert items["liquidity_neutral_momentum_guard_price_volume"].evidence_scope == "OHLCV_ONLY"
    assert items["liquidity_neutral_momentum_guard_price_volume"].evidence_path_status == "PASS"
    assert items["defensive_cash_guard_price_volume"].status == "READY"
    assert items["defensive_cash_guard_price_volume"].evidence_scope == "OHLCV_ONLY"
    assert items["defensive_cash_guard_price_volume"].evidence_path_status == "PASS"
    assert items["risk_off_cash_stop_price_volume"].status == "READY"
    assert items["risk_off_cash_stop_price_volume"].evidence_scope == "OHLCV_ONLY"
    assert items["risk_off_cash_stop_price_volume"].evidence_path_status == "PASS"
    assert items["regime_pause_price_volume"].status == "READY"
    assert items["regime_pause_price_volume"].evidence_scope == "OHLCV_ONLY"
    assert items["regime_pause_price_volume"].evidence_path_status == "PASS"
    assert items["price_volume_defensive"].source_provenance.startswith(
        "source=unit-test vendor / unit-test terminal"
    )
    assert items["price_volume_defensive"].intended_regimes
    assert items["price_volume_defensive"].market_regime_fit_status == "NOT_REVIEWED"
    assert items["price_volume_defensive"].market_regime_fit == "not_reviewed"
    assert "Audited OHLCV bars" in items["price_volume_defensive"].required_evidence_notes[0]
    assert items["price_volume_defensive"].warnings
    assert items["core_multifactor"].status == "BLOCKED"
    assert items["core_multifactor"].evidence_scope == "PIT_FUNDAMENTAL_REQUIRED"
    assert items["core_multifactor"].evidence_path_status == "BLOCK"
    assert any("point-in-time" in note for note in items["core_multifactor"].required_evidence_notes)
    assert any("pit_fundamental_candidate_path" in blocker for blocker in items["core_multifactor"].blocked_by)
    assert any("price_volume_defensive" in action for action in readiness.next_actions)

    out = write_candidate_experiment_readiness(readiness, tmp_path / "out")
    matrix = list(csv.DictReader((out / "candidate_experiment_readiness_matrix.csv").open(encoding="utf-8")))
    assert matrix[0]["candidate"] == "price_volume_defensive"
    assert matrix[0]["status"] == "READY"
    assert matrix[0]["evidence_scope"] == "OHLCV_ONLY"
    assert matrix[0]["evidence_path_status"] == "PASS"
    assert "defensive" in matrix[0]["intended_regimes"]
    assert matrix[0]["market_regime_fit_status"] == "NOT_REVIEWED"
    assert matrix[0]["first_blocker"] == ""
    assert matrix[0]["next_command"].startswith("python examples/run_candidate_experiment_evidence.py")


def test_candidate_experiment_readiness_blocks_risk_off_regime_fit(
    tmp_path: Path,
) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    readiness = build_candidate_experiment_readiness(
        queue,
        stage_statuses={
            "candidate_experiment_queue": "PASS",
            "offline_data_package": "PASS",
            "source_qa_preflight": "PASS",
            "data_source_qa_review": "PASS",
            "offline_data_intake": "PASS",
        },
        handoff_payload={
            "evidence_paths": [
                {"name": "ohlcv_minimum_path", "status": "PASS", "blocked_by": []},
                {"name": "pit_fundamental_candidate_path", "status": "PASS", "blocked_by": []},
            ]
        },
        market_context={
            "source": "market_regime",
            "payload": {"status": "PASS", "label": "risk_off", "as_of": "2026-06-08"},
            "artifact": str(tmp_path / "market_regime.json"),
        },
        as_of="2026-06-08",
    )

    assert readiness.decision == "BLOCK"
    assert readiness.runnable_count == 0
    assert all(item.market_regime_fit_status == "BLOCK" for item in readiness.items)
    assert all(item.market_regime_fit == "risk_off_pause" for item in readiness.items)
    assert any("risk_off" in blocker for blocker in readiness.blockers)


def test_candidate_experiment_readiness_blocks_ohlcv_candidate_when_package_blocks(
    tmp_path: Path,
) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    readiness = build_candidate_experiment_readiness(
        queue,
        stage_statuses={
            "candidate_experiment_queue": "PASS",
            "offline_data_package": "WATCH",
            "source_qa_preflight": "PASS",
            "data_source_qa_review": "PASS",
            "offline_data_intake": "WATCH",
        },
        handoff_payload={
            "evidence_paths": [
                {
                    "name": "ohlcv_minimum_path",
                    "status": "PASS",
                    "blocked_by": [],
                    "required_evidence": ["Audited OHLCV bars and source QA evidence."],
                },
                {
                    "name": "pit_fundamental_candidate_path",
                    "status": "BLOCK",
                    "blocked_by": ["fundamentals.csv is missing."],
                    "required_evidence": ["PIT fundamentals evidence."],
                },
            ]
        },
        source_metadata_summary=_source_summary(),
        market_context={
            "source": "market_regime",
            "payload": {"status": "PASS", "label": "neutral", "as_of": "2026-06-08"},
            "artifact": str(tmp_path / "market_regime.json"),
        },
        ohlcv_package_payload={
            "decision": "BLOCK",
            "candidate": "price_volume_defensive",
            "blockers": [
                "bars_coverage: bars.csv coverage is below the OHLCV research minimum: symbols=2/300."
            ],
            "watch_items": [],
        },
        as_of="2026-06-08",
    )

    price_volume = next(item for item in readiness.items if item.candidate == "price_volume_defensive")
    assert readiness.decision == "BLOCK"
    assert readiness.runnable_count == 0
    assert price_volume.status == "BLOCKED"
    assert any("ohlcv_experiment_package=BLOCK" in blocker for blocker in price_volume.blocked_by)
    assert any("ohlcv_experiment_package.json" in action for action in readiness.next_actions)


def test_candidate_experiment_readiness_surfaces_handoff_preview_blocker(
    tmp_path: Path,
) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    readiness = build_candidate_experiment_readiness(
        queue,
        stage_statuses={
            "candidate_experiment_queue": "PASS",
            "offline_data_package": "PASS",
            "source_qa_preflight": "PASS",
            "data_source_qa_review": "PASS",
            "offline_data_intake": "PASS",
        },
        handoff_payload={
            "evidence_paths": [
                {
                    "name": "ohlcv_minimum_path",
                    "status": "BLOCK",
                    "blocked_by": [
                        "bars.csv preview is BLOCK: Required columns could not be mapped. Missing columns=close."
                    ],
                    "required_evidence": ["Non-template recent A-share daily bars."],
                },
                {
                    "name": "pit_fundamental_candidate_path",
                    "status": "BLOCK",
                    "blocked_by": ["fundamentals.csv is missing."],
                    "required_evidence": ["PIT fundamentals evidence."],
                },
            ]
        },
        as_of="2026-06-08",
    )

    price_volume = next(item for item in readiness.items if item.candidate == "price_volume_defensive")
    assert readiness.decision == "BLOCK"
    assert price_volume.status == "BLOCKED"
    assert any("bars.csv preview is BLOCK" in blocker for blocker in price_volume.blocked_by)
    assert any("OHLCV-only path" in action for action in readiness.next_actions)


def test_candidate_experiment_readiness_cli_reads_report(tmp_path: Path) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    queue_payload = queue.to_dict()
    (tmp_path / "candidate_experiment_queue.json").write_text(
        json.dumps(queue_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "first_million_pipeline.json").write_text(
        json.dumps(
            {
                "stages": [
                    {"name": "candidate_experiment_queue", "status": "PASS", "message": "queue"},
                    {"name": "source_qa_preflight", "status": "BLOCK", "message": "preflight blocked"},
                    {
                        "name": "offline_data_package",
                        "status": "BLOCK",
                        "message": "package blocked",
                    },
                    {
                        "name": "data_source_qa_review",
                        "status": "BLOCK",
                        "message": "SOURCE_QA_ANSWERS_MISSING",
                    },
                    {"name": "offline_data_intake", "status": "BLOCK", "message": "stopped"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "offline_data_package.json").write_text(
        json.dumps({"source_metadata_summary": _source_summary()}, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "real_data_handoff_checklist.json").write_text(
        json.dumps(
            {
                "evidence_paths": [
                    {
                        "name": "ohlcv_minimum_path",
                        "status": "PASS",
                        "blocked_by": [],
                        "required_evidence": ["Audited OHLCV bars and source QA evidence."],
                    },
                    {
                        "name": "pit_fundamental_candidate_path",
                        "status": "BLOCK",
                        "blocked_by": ["fundamentals.csv is missing."],
                        "required_evidence": ["PIT fundamentals evidence."],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_experiment_readiness.py",
            "--report-dir",
            str(tmp_path),
            "--as-of",
            "2026-06-08",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    readiness = build_candidate_experiment_readiness_from_report(tmp_path, as_of="2026-06-08")
    payload = json.loads((tmp_path / "candidate_experiment_readiness.json").read_text(encoding="utf-8"))
    assert readiness.decision == "BLOCK"
    assert payload["blocked_count"] == 18
    assert payload["scope_summary"]["OHLCV_ONLY"]["blocked"] == 13
    assert payload["scope_summary"]["PIT_FUNDAMENTAL_REQUIRED"]["blocked"] == 5
    first_item = payload["items"][0]
    assert first_item["source_provenance"].startswith("source=unit-test vendor / unit-test terminal")
    assert first_item["evidence_path_status"] == "PASS"
    assert "Audited OHLCV bars" in "\n".join(first_item["required_evidence_notes"])
    matrix = list(csv.DictReader((tmp_path / "candidate_experiment_readiness_matrix.csv").open(encoding="utf-8")))
    assert matrix[0]["candidate"] == "price_volume_defensive"
    assert matrix[0]["evidence_scope"] == "OHLCV_ONLY"
    assert matrix[0]["status"] == "BLOCKED"
    assert "source_qa_preflight=BLOCK" in matrix[0]["first_blocker"]


def _source_summary() -> dict[str, str]:
    return {
        "data_vendor_or_broker": "unit-test vendor",
        "terminal_or_product_name": "unit-test terminal",
        "exported_at_local_time": "2024-01-03 18:00:00",
        "price_adjustment": "qfq",
        "reviewed_by": "tester",
        "reviewed_at": "2024-01-03",
    }


def _write_pipeline_stages(root: Path, *, status: str) -> None:
    _write_json(
        root / "first_million_pipeline.json",
        {
            "stages": [
                {"name": "candidate_experiment_queue", "status": "PASS", "message": "queue"},
                {"name": "offline_data_package", "status": status, "message": "package"},
                {"name": "source_qa_preflight", "status": "PASS", "message": "preflight"},
                {"name": "data_source_qa_review", "status": "PASS", "message": "qa"},
                {"name": "offline_data_intake", "status": status, "message": "intake"},
            ]
        },
    )


def _write_handoff_paths(root: Path, *, ohlcv_status: str, pit_status: str) -> None:
    _write_json(
        root / "real_data_handoff_checklist.json",
        {
            "evidence_paths": [
                {
                    "name": "ohlcv_minimum_path",
                    "status": ohlcv_status,
                    "blocked_by": [] if ohlcv_status == "PASS" else ["bars.csv is not ready."],
                    "required_evidence": ["Audited OHLCV bars and source QA evidence."],
                },
                {
                    "name": "pit_fundamental_candidate_path",
                    "status": pit_status,
                    "blocked_by": [] if pit_status == "PASS" else ["fundamentals.csv is missing."],
                    "required_evidence": ["PIT fundamentals evidence."],
                },
            ]
        },
    )


def _write_offline_package(root: Path) -> None:
    _write_json(
        root / "offline_data_package.json",
        {"source_metadata_summary": _source_summary()},
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _cfg(cache_path: Path) -> Config:
    return Config(
        {
            "research": {
                "start": "2024-01-02",
                "end": "2024-01-03",
                "initial_cash": 1_000_000.0,
                "rebalance": "monthly",
            },
            "universe": {
                "mode": "all_a",
                "index_code": "000906",
                "include_st": False,
                "min_history_days": 1,
            },
            "strategy": {"n_holdings": 5, "max_weight": 0.10},
            "broker": {
                "commission_rate": 0.0,
                "min_commission": 0.0,
                "stamp_tax": 0.0,
                "slippage_bps": 0.0,
                "price_limit_pct": 0.10,
                "lot_size": 100,
            },
            "risk": {"max_drawdown_stop": 0.2},
            "data": {"cache_path": str(cache_path), "source": "csv"},
            "output": {"results_dir": str(cache_path.parent)},
        }
    )
