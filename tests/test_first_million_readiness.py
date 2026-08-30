from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.storage import BarStorage
from quantify.ops.first_million_readiness import (
    build_first_million_readiness_card,
    write_first_million_readiness_card,
)
from quantify.utils.config import Config


def test_first_million_readiness_blocks_missing_artifacts(tmp_path: Path) -> None:
    card = build_first_million_readiness_card(tmp_path, as_of="2026-06-08")
    out = write_first_million_readiness_card(card, tmp_path)

    payload = json.loads((out / "first_million_readiness.json").read_text(encoding="utf-8"))
    markdown = (out / "first_million_readiness.md").read_text(encoding="utf-8")
    assert payload["decision"] == "BLOCK"
    assert payload["gates"][0]["status"] == "MISSING"
    assert payload["gates"][0]["name"] == "recent_data_acquisition_plan"
    assert payload["next_actions"][0] == "Run recent data acquisition plan."
    assert any("Do not start strategy search" in item for item in payload["prohibited_actions"])
    assert "not a strategy recommendation" in markdown
    assert "profit-claim wording" in markdown


def test_first_million_readiness_passes_when_core_gates_pass(tmp_path: Path) -> None:
    _write_pass_artifacts(tmp_path)

    card = build_first_million_readiness_card(tmp_path, as_of="2026-06-08")

    assert card.decision == "PASS"
    assert card.blockers == []
    gate_names = [gate.name for gate in card.gates]
    assert "provider_smoke_readiness" in gate_names
    ramp_gate = next(gate for gate in card.gates if gate.name == "provider_acquisition_ramp")
    assert ramp_gate.status == "PASS"
    assert ramp_gate.artifact == "not_applicable"
    assert "optional route diagnostic is not a data gate" in ramp_gate.message
    assert "data_evidence_action_packet" in gate_names
    assert "operator_handoff_status" in gate_names
    assert "csv_intake_preview" in gate_names
    assert "offline_data_package" in gate_names
    assert "real_data_handoff_checklist" in gate_names
    assert "source_qa_preflight" in gate_names
    assert "run_manifest" in gate_names
    assert "micro_live_readiness" in gate_names
    assert "capital_scaling_plan" in gate_names
    assert card.gates[-1].name == "compounding_path_review"


def test_first_million_readiness_blocks_when_current_cache_is_not_ready(tmp_path: Path) -> None:
    _write_pass_artifacts(tmp_path)
    cache = tmp_path / "recent.db"
    BarStorage(cache)

    card = build_first_million_readiness_card(
        tmp_path,
        as_of="2026-06-08",
        cfg=_cfg(cache),
        min_symbols=300,
        min_trading_days=240,
    )

    gates = {gate.name: gate for gate in card.gates}

    assert card.decision == "BLOCK"
    assert gates["research_cache_admissibility"].status == "BLOCK"
    assert "symbols=0" in gates["research_cache_admissibility"].message
    assert gates["current_data_cache"].status == "BLOCK"
    assert "symbols=0" in gates["current_data_cache"].message
    assert gates["promotion_metadata_check"].status == "BLOCK"
    assert card.next_actions == ["Refresh/import recent real A-share data, then rerun first-million readiness."]


def test_first_million_readiness_current_cache_passes_when_recent_and_broad(tmp_path: Path) -> None:
    _write_pass_artifacts(tmp_path)
    cache = tmp_path / "recent.db"
    _write_recent_cache(cache)

    card = build_first_million_readiness_card(
        tmp_path,
        as_of="2024-01-05",
        cfg=_cfg(cache),
        min_symbols=2,
        min_trading_days=3,
    )

    research_cache = next(gate for gate in card.gates if gate.name == "research_cache_admissibility")
    current_cache = next(gate for gate in card.gates if gate.name == "current_data_cache")
    assert card.decision == "PASS"
    assert research_cache.status == "PASS"
    assert "Research cache is admissible" in research_cache.message
    assert current_cache.status == "PASS"
    assert "symbols=2" in current_cache.message


def test_first_million_readiness_blocks_current_cache_without_csv_fingerprint(
    tmp_path: Path,
) -> None:
    _write_pass_artifacts(tmp_path)
    cache = tmp_path / "recent.db"
    _write_recent_cache(cache, with_metadata=False)

    card = build_first_million_readiness_card(
        tmp_path,
        as_of="2024-01-05",
        cfg=_cfg(cache),
        min_symbols=2,
        min_trading_days=3,
    )

    research_cache = next(gate for gate in card.gates if gate.name == "research_cache_admissibility")
    current_cache = next(gate for gate in card.gates if gate.name == "current_data_cache")
    assert card.decision == "BLOCK"
    assert research_cache.status == "PASS"
    assert current_cache.status == "BLOCK"
    assert "Missing csv_dataset_fingerprint" in current_cache.message
    assert card.next_actions == [
        "Rerun guarded offline intake so the cache records CSV fingerprint, "
        "PASS source QA metadata, and provenance hashes."
    ]


def test_first_million_readiness_blocks_current_cache_without_source_qa_metadata(
    tmp_path: Path,
) -> None:
    _write_pass_artifacts(tmp_path)
    cache = tmp_path / "recent.db"
    _write_recent_cache(
        cache,
        metadata={
            "csv_dataset_fingerprint": "unit-test-csv-fingerprint",
            "data_source_qa_status": "WATCH",
            "data_source_csv_qa_status": "PASS",
            **_source_qa_metadata(tmp_path),
        },
    )

    card = build_first_million_readiness_card(
        tmp_path,
        as_of="2024-01-05",
        cfg=_cfg(cache),
        min_symbols=2,
        min_trading_days=3,
    )

    current_cache = next(gate for gate in card.gates if gate.name == "current_data_cache")
    assert card.decision == "BLOCK"
    assert current_cache.status == "BLOCK"
    assert "data_source_qa_status is WATCH" in current_cache.message


def test_first_million_readiness_blocks_current_cache_without_source_qa_fingerprints(
    tmp_path: Path,
) -> None:
    _write_pass_artifacts(tmp_path)
    cache = tmp_path / "recent.db"
    _write_recent_cache(
        cache,
        metadata={
            "csv_dataset_fingerprint": "unit-test-csv-fingerprint",
            "data_source_qa_status": "PASS",
            "data_source_csv_qa_status": "PASS",
        },
    )

    card = build_first_million_readiness_card(
        tmp_path,
        as_of="2024-01-05",
        cfg=_cfg(cache),
        min_symbols=2,
        min_trading_days=3,
    )

    current_cache = next(gate for gate in card.gates if gate.name == "current_data_cache")
    assert card.decision == "BLOCK"
    assert current_cache.status == "BLOCK"
    assert "Missing data_source_qa_checklist_path" in current_cache.message


def test_first_million_readiness_blocks_current_cache_when_source_qa_hash_is_stale(
    tmp_path: Path,
) -> None:
    _write_pass_artifacts(tmp_path)
    cache = tmp_path / "recent.db"
    metadata = _source_qa_metadata(tmp_path)
    checklist = Path(metadata["data_source_qa_checklist_path"])
    checklist.write_text('{"changed": true}', encoding="utf-8")
    _write_recent_cache(
        cache,
        metadata={
            "csv_dataset_fingerprint": "unit-test-csv-fingerprint",
            "data_source_qa_status": "PASS",
            "data_source_csv_qa_status": "PASS",
            **metadata,
        },
    )

    card = build_first_million_readiness_card(
        tmp_path,
        as_of="2024-01-05",
        cfg=_cfg(cache),
        min_symbols=2,
        min_trading_days=3,
    )

    current_cache = next(gate for gate in card.gates if gate.name == "current_data_cache")
    assert card.decision == "BLOCK"
    assert current_cache.status == "BLOCK"
    assert "does not match current source QA checklist file hash" in current_cache.message


def test_first_million_readiness_blocks_strict_manifest_without_manifest_metadata(
    tmp_path: Path,
) -> None:
    _write_pass_artifacts(tmp_path)
    cache = tmp_path / "recent.db"
    _write_recent_cache(
        cache,
        metadata={
            "csv_dataset_fingerprint": "unit-test-csv-fingerprint",
            "data_source_qa_status": "PASS",
            "data_source_csv_qa_status": "PASS",
            "data_source_qa_require_evidence_manifest": "True",
            **_source_qa_metadata(tmp_path),
        },
    )

    card = build_first_million_readiness_card(
        tmp_path,
        as_of="2024-01-05",
        cfg=_cfg(cache),
        min_symbols=2,
        min_trading_days=3,
    )

    current_cache = next(gate for gate in card.gates if gate.name == "current_data_cache")
    assert card.decision == "BLOCK"
    assert current_cache.status == "BLOCK"
    assert "Missing data_source_qa_evidence_manifest_path" in current_cache.message


def test_first_million_readiness_blocks_stale_strict_manifest(
    tmp_path: Path,
) -> None:
    _write_pass_artifacts(tmp_path)
    cache = tmp_path / "recent.db"
    metadata = _source_qa_metadata(tmp_path)
    manifest = tmp_path / "qa" / "source_qa_evidence_manifest.json"
    manifest.write_text('{"items": []}', encoding="utf-8")
    metadata.update(
        {
            "data_source_qa_require_evidence_manifest": "True",
            "data_source_qa_evidence_manifest_path": str(manifest),
            "data_source_qa_evidence_manifest_sha256": _sha256(manifest),
        }
    )
    manifest.write_text('{"items": [{"id": "changed"}]}', encoding="utf-8")
    _write_recent_cache(
        cache,
        metadata={
            "csv_dataset_fingerprint": "unit-test-csv-fingerprint",
            "data_source_qa_status": "PASS",
            "data_source_csv_qa_status": "PASS",
            **metadata,
        },
    )

    card = build_first_million_readiness_card(
        tmp_path,
        as_of="2024-01-05",
        cfg=_cfg(cache),
        min_symbols=2,
        min_trading_days=3,
    )

    current_cache = next(gate for gate in card.gates if gate.name == "current_data_cache")
    assert card.decision == "BLOCK"
    assert current_cache.status == "BLOCK"
    assert "does not match current source QA evidence manifest file hash" in current_cache.message


def test_first_million_readiness_surfaces_source_provenance(tmp_path: Path) -> None:
    _write_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "offline_data_package.json",
        {
            "status": "PASS",
            "items": [],
            "source_metadata_summary": {
                "data_vendor_or_broker": "unit-test vendor",
                "terminal_or_product_name": "unit-test terminal",
                "exported_at_local_time": "2026-06-08 18:00:00",
                "price_adjustment": "qfq",
                "reviewed_by": "tester",
                "reviewed_at": "2026-06-08",
            },
            "next_actions": ["Run guarded offline data intake."],
        },
    )
    _write_json(
        tmp_path / "source_qa" / "data_source_qa_review.json",
        {
            "status": "PASS",
            "source_metadata": {
                "data_vendor_or_broker": "unit-test vendor",
                "terminal_or_product_name": "unit-test terminal",
                "exported_at_local_time": "2026-06-08 18:00:00",
                "price_adjustment": "qfq",
                "reviewed_by": "tester",
                "reviewed_at": "2026-06-08",
            },
            "findings": [],
            "next_actions": ["Continue to CSV doctor."],
        },
    )

    card = build_first_million_readiness_card(tmp_path, as_of="2026-06-08")

    package_gate = next(gate for gate in card.gates if gate.name == "offline_data_package")
    source_gate = next(gate for gate in card.gates if gate.name == "data_source_qa_review")
    assert "source=unit-test vendor / unit-test terminal" in package_gate.message
    assert "exported_at=2026-06-08 18:00:00" in package_gate.message
    assert "reviewed_by=tester at 2026-06-08" in source_gate.message


def test_first_million_readiness_blocks_source_qa_preflight(
    tmp_path: Path,
) -> None:
    _write_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "source_qa" / "source_qa_preflight.json",
        {
            "status": "BLOCK",
            "items": [
                {
                    "kind": "metadata",
                    "status": "BLOCK",
                    "field": "data_vendor_or_broker",
                    "message": "Required source metadata is missing.",
                    "fix": "Fill the field.",
                }
            ],
            "next_commands": ["run source preflight again"],
        },
    )

    card = build_first_million_readiness_card(tmp_path, as_of="2026-06-08")
    gate = next(gate for gate in card.gates if gate.name == "source_qa_preflight")

    assert card.decision == "BLOCK"
    assert gate.status == "BLOCK"
    assert "data_vendor_or_broker" in gate.message
    assert card.next_actions == ["run source preflight again"]


def test_first_million_readiness_surfaces_data_evidence_packet_blocker(
    tmp_path: Path,
) -> None:
    _write_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "data_evidence_action_packet.json",
        {
            "decision": "BLOCK",
            "current_blockers": [
                {
                    "name": "csv_template_rows",
                    "status": "BLOCK",
                    "message": "Generated template rows remain in bars.csv.",
                    "next_action": "Replace data_exports CSV templates with real vendor exports.",
                }
            ],
            "watch_items": [],
            "immediate_commands": ["run packet command"],
        },
    )

    card = build_first_million_readiness_card(tmp_path, as_of="2026-06-08")
    gate = next(gate for gate in card.gates if gate.name == "data_evidence_action_packet")

    assert card.decision == "BLOCK"
    assert gate.status == "BLOCK"
    assert "csv_template_rows" in gate.message
    assert card.next_actions == ["Replace data_exports CSV templates with real vendor exports."]


def test_first_million_readiness_surfaces_operator_handoff_open_tasks(
    tmp_path: Path,
) -> None:
    _write_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "operator_handoff_status.json",
        {
            "status": "BLOCK",
            "open_task_count": 17,
            "p0_open_task_count": 17,
            "source_qa_open_task_count": 11,
            "source_qa_attachment_open_task_count": 5,
            "data_export_open_task_count": 6,
            "next_actions": ["Fill source QA worksheet rows first."],
        },
    )

    card = build_first_million_readiness_card(tmp_path, as_of="2026-06-08")
    gate = next(gate for gate in card.gates if gate.name == "operator_handoff_status")

    assert card.decision == "BLOCK"
    assert gate.status == "BLOCK"
    assert "open_tasks=17" in gate.message
    assert "source_qa=11" in gate.message
    assert "source_qa_attachment=5" in gate.message
    assert card.next_actions == ["Fill source QA worksheet rows first."]


def test_first_million_readiness_surfaces_csv_preview_blocker(
    tmp_path: Path,
) -> None:
    _write_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "csv_intake_preview.json",
        {
            "status": "BLOCK",
            "items": [
                {
                    "role": "bars",
                    "file_name": "bars.csv",
                    "status": "BLOCK",
                    "message": "Required columns could not be mapped into the research schema.",
                    "missing_columns": ["close"],
                }
            ],
            "next_actions": ["Fix bars.csv before import."],
        },
    )

    card = build_first_million_readiness_card(tmp_path, as_of="2026-06-08")
    gate = next(gate for gate in card.gates if gate.name == "csv_intake_preview")

    assert card.decision == "BLOCK"
    assert gate.status == "BLOCK"
    assert "bars.csv" in gate.message
    assert card.next_actions == ["Fix bars.csv before import."]


def test_first_million_readiness_watches_watch_gate(tmp_path: Path) -> None:
    _write_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "candidate_experiment_completion.json",
        {
            "decision": "WATCH",
            "selected_candidate": "core_multifactor",
            "watch_items": ["llm_review.json: missing evidence"],
            "next_actions": ["Review WATCH artifacts manually before paper-stage planning."],
        },
    )

    card = build_first_million_readiness_card(tmp_path, as_of="2026-06-08")

    assert card.decision == "WATCH"
    assert any("candidate_experiment_completion" in item for item in card.watch_items)
    assert card.next_actions == ["Review WATCH artifacts manually before paper-stage planning."]


def test_first_million_readiness_blocks_missing_run_manifest(tmp_path: Path) -> None:
    _write_pass_artifacts(tmp_path)
    (tmp_path / "run_manifest.json").unlink()

    card = build_first_million_readiness_card(tmp_path, as_of="2026-06-08")
    gate = next(gate for gate in card.gates if gate.name == "run_manifest")

    assert card.decision == "BLOCK"
    assert gate.status == "MISSING"
    assert "run_manifest.json is missing" in gate.message
    assert card.next_actions == [
        "Rerun first-million pipeline or weekly pipeline to generate run_manifest.json."
    ]


def test_first_million_readiness_blocks_run_manifest_without_provenance(
    tmp_path: Path,
) -> None:
    _write_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "run_manifest.json",
        {
            "demo_data_used": False,
            "in_sample_end": "2024-01-02",
            "out_sample_start": "2024-01-03",
            "data_version": {"data_source_qa_status": "PASS"},
        },
    )

    card = build_first_million_readiness_card(tmp_path, as_of="2026-06-08")
    gate = next(gate for gate in card.gates if gate.name == "run_manifest")

    assert card.decision == "BLOCK"
    assert gate.status == "BLOCK"
    assert "run_manifest provenance blocker" in gate.message


def test_first_million_readiness_surfaces_downstream_readiness_blockers(
    tmp_path: Path,
) -> None:
    _write_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "micro_live_readiness.json",
        {
            "decision": "BLOCK",
            "findings": [
                {
                    "severity": "BLOCK",
                    "code": "MISSING_APPROVAL",
                    "message": "approval_record.json is required.",
                }
            ],
        },
    )
    _write_json(
        tmp_path / "capital_scaling_plan.json",
        {
            "decision": "BLOCK",
            "blockers": ["micro_live_readiness is BLOCK (micro_live_readiness.json)."],
        },
    )

    card = build_first_million_readiness_card(tmp_path, as_of="2026-06-08")
    gates = {gate.name: gate for gate in card.gates}

    assert card.decision == "BLOCK"
    assert gates["micro_live_readiness"].status == "BLOCK"
    assert "MISSING_APPROVAL" in gates["micro_live_readiness"].message
    assert gates["capital_scaling_plan"].status == "BLOCK"
    assert "micro_live_readiness is BLOCK" in gates["capital_scaling_plan"].message


def test_first_million_readiness_surfaces_statistical_contract_blocker(tmp_path: Path) -> None:
    _write_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "micro_live_readiness.json",
        {
            "decision": "BLOCK",
            "findings": [
                {
                    "severity": "BLOCK",
                    "code": "BENCHMARK_REPORT_CONTRACT_INVALID",
                    "message": "benchmark_report.json fails its retained-evidence contract.",
                }
            ],
        },
    )

    card = build_first_million_readiness_card(tmp_path, as_of="2026-06-08")
    gate = next(gate for gate in card.gates if gate.name == "micro_live_readiness")

    assert card.decision == "BLOCK"
    assert gate.status == "BLOCK"
    assert "BENCHMARK_REPORT_CONTRACT_INVALID" in gate.message


def test_first_million_readiness_prefers_offline_path_after_network_blocked_import(
    tmp_path: Path,
) -> None:
    _write_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "recent_data_acquisition_plan.json",
        {
            "status": "BLOCK",
            "current_symbol_count": 0,
            "current_latest_bar_date": "",
            "blockers": ["Current cache is not ready for recent A-share research evidence."],
            "latest_import_attempt": {
                "status": "BLOCK",
                "network_blocked": True,
                "message": "AKShare import was blocked by network/proxy access; no real market cache was created.",
                "failure_stage": "symbol_list",
                "recommended_route": "offline_csv_or_tdx",
                "path": "results/import/smoke/data_import.json",
                "next_action": (
                    "Use the offline CSV path: fill data_source_qa_answers.json with real "
                    "vendor/export evidence, replace data_exports CSV templates, then run guarded "
                    "offline intake."
                ),
            },
            "steps": [{"command": "try akshare again"}],
        },
    )

    card = build_first_million_readiness_card(tmp_path, as_of="2026-06-08")

    assert card.decision == "BLOCK"
    assert "network/proxy" in card.gates[0].message
    assert "failure_stage=symbol_list" in card.gates[0].message
    assert "recommended_route=offline_csv_or_tdx" in card.gates[0].message
    assert "offline CSV" in card.next_actions[0]
    assert "data_source_qa_answers.json" in card.next_actions[0]


def test_first_million_readiness_provider_smoke_block_is_diagnostic(
    tmp_path: Path,
) -> None:
    _write_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "provider_smoke_readiness.json",
        {
            "status": "BLOCK",
            "provider": "akshare",
            "endpoint_viability": "BLOCK",
            "data_sufficiency_status": "BLOCK",
            "imported_symbols": 0,
            "requested_symbols": 2,
            "network_blocked": True,
            "recommended_route": "offline_csv_or_tdx",
            "next_actions": ["Use guarded offline CSV/TDX intake until provider access is fixed."],
        },
    )

    card = build_first_million_readiness_card(tmp_path, as_of="2026-06-08")
    gate = next(gate for gate in card.gates if gate.name == "provider_smoke_readiness")

    assert card.decision == "WATCH"
    assert gate.status == "WATCH"
    assert "network/proxy" in gate.message
    assert card.next_actions == ["Use guarded offline CSV/TDX intake until provider access is fixed."]


def test_first_million_readiness_provider_ramp_block_is_route_diagnostic(
    tmp_path: Path,
) -> None:
    _write_pass_artifacts(tmp_path)
    _write_provider_ramp_report(tmp_path / "provider_acquisition_ramp.json", status="BLOCK")

    card = build_first_million_readiness_card(tmp_path, as_of="2026-06-08")
    gate = next(gate for gate in card.gates if gate.name == "provider_acquisition_ramp")

    assert card.decision == "WATCH"
    assert gate.status == "WATCH"
    assert "route diagnostics only" in gate.message
    assert "cannot approve source QA" in gate.message
    assert "promotion gates" in gate.message
    assert card.next_actions == ["Review provider ramp before broad provider imports."]


def test_first_million_readiness_cli_returns_nonzero_on_block(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_first_million_readiness.py",
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

    payload = json.loads((tmp_path / "first_million_readiness.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"


def test_first_million_readiness_cli_checks_current_cache_when_config_is_supplied(tmp_path: Path) -> None:
    _write_pass_artifacts(tmp_path)
    cache = tmp_path / "recent.db"
    BarStorage(cache)
    config = tmp_path / "research_recent.yaml"
    _write_config(config, cache)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_first_million_readiness.py",
            "--report-dir",
            str(tmp_path),
            "--config",
            str(config),
            "--as-of",
            "2026-06-08",
            "--min-symbols",
            "300",
            "--min-trading-days",
            "240",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((tmp_path / "first_million_readiness.json").read_text(encoding="utf-8"))
    gate_names = [gate["name"] for gate in payload["gates"]]
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"
    assert "research_cache_admissibility" in gate_names
    assert "current_data_cache" in gate_names
    assert "promotion_metadata_check" in gate_names


def _write_pass_artifacts(root: Path) -> None:
    _write_json(
        root / "recent_data_acquisition_plan.json",
        {
            "status": "PASS",
            "current_symbol_count": 300,
            "current_latest_bar_date": "2026-06-05",
            "blockers": [],
            "steps": [{"command": "run next"}],
        },
    )
    _write_json(
        root / "provider_smoke_readiness.json",
        {
            "status": "PASS",
            "provider": "akshare",
            "endpoint_viability": "PASS",
            "data_sufficiency_status": "PASS",
            "requested_symbols": 300,
            "imported_symbols": 300,
            "failed_symbols": 0,
            "bar_rows": 72000,
            "calendar_days": 240,
            "network_blocked": False,
            "recommended_route": "provider_broad_import_then_bootstrap",
            "next_actions": ["Continue deterministic gates."],
        },
    )
    _write_json(
        root / "data_gap_action_plan.json",
        {"decision": "PASS", "items": [], "next_actions": ["Run guarded offline data intake."]},
    )
    _write_json(
        root / "data_evidence_action_packet.json",
        {
            "decision": "PASS",
            "current_blockers": [],
            "watch_items": [],
            "immediate_commands": ["Run guarded offline data intake."],
        },
    )
    _write_json(
        root / "operator_handoff_status.json",
        {
            "status": "PASS",
            "open_task_count": 0,
            "p0_open_task_count": 0,
            "source_qa_open_task_count": 0,
            "data_export_open_task_count": 0,
            "next_actions": ["Continue deterministic gates."],
        },
    )
    _write_json(
        root / "csv_intake_preview.json",
        {
            "status": "PASS",
            "items": [
                {
                    "role": "bars",
                    "file_name": "bars.csv",
                    "status": "PASS",
                    "normalized_rows": 60000,
                    "symbol_count": 300,
                    "message": "Columns mapped and normalized successfully.",
                }
            ],
            "next_actions": ["Run CSV validation before guarded offline intake."],
        },
    )
    _write_json(
        root / "offline_data_package.json",
        {"status": "PASS", "items": [], "next_actions": ["Run guarded offline data intake."]},
    )
    _write_json(
        root / "real_data_handoff_checklist.json",
        {
            "status": "PASS",
            "evidence_paths": [
                {
                    "name": "ohlcv_minimum_path",
                    "status": "PASS",
                    "blocked_by": [],
                    "next_action": "Run guarded offline data intake.",
                },
                {
                    "name": "pit_fundamental_candidate_path",
                    "status": "PASS",
                    "blocked_by": [],
                    "next_action": "Run full candidate comparison.",
                },
            ],
            "next_actions": ["Run guarded offline data intake."],
        },
    )
    _write_json(
        root / "source_qa" / "data_source_qa_review.json",
        {"status": "PASS", "findings": [], "next_actions": ["Continue to CSV doctor."]},
    )
    _write_json(
        root / "source_qa" / "source_qa_preflight.json",
        {"status": "PASS", "items": [], "next_commands": ["Run data source QA review."]},
    )
    _write_json(
        root / "offline_intake" / "offline_data_intake.json",
        {"status": "PASS", "steps": [], "next_actions": ["Continue to candidate experiment readiness."]},
    )
    _write_json(
        root / "market_context_readiness.json",
        {
            "decision": "PASS",
            "source": "market_regime",
            "label": "neutral",
            "artifact": str(root / "market_regime.json"),
            "artifact_status": "PASS",
            "artifact_as_of": "2026-06-08",
            "target_as_of": "2026-06-08",
            "findings": [],
            "blockers": [],
            "watch_items": [],
            "next_actions": ["Continue candidate experiment readiness."],
        },
    )
    _write_json(
        root / "candidate_experiment_readiness.json",
        {
            "decision": "PASS",
            "runnable_count": 5,
            "blockers": [],
            "next_actions": ["Run the first queued candidate experiment command."],
        },
    )
    _write_json(
        root / "candidate_experiment_launch.json",
        {
            "decision": "PASS",
            "selected_candidate": "core_multifactor",
            "run_id": "20260608_core_multifactor",
            "blocked_by": [],
            "next_actions": ["Run the command sequence in order."],
        },
    )
    _write_json(
        root / "candidate_experiment_execution.json",
        {
            "decision": "PASS",
            "selected_candidate": "core_multifactor",
            "run_id": "20260608_core_multifactor",
            "steps": [{"status": "PASS", "returncode": 0}],
            "blockers": [],
            "next_actions": ["Run candidate_experiment_completion to verify required artifacts."],
        },
    )
    _write_json(
        root / "candidate_experiment_completion.json",
        {
            "decision": "PASS",
            "selected_candidate": "core_multifactor",
            "run_id": "20260608_core_multifactor",
            "blockers": [],
            "watch_items": [],
            "next_actions": ["Archive the experiment directory."],
        },
    )
    _write_json(
        root / "run_manifest.json",
        {
            "demo_data_used": False,
            "latest_bar_date": "2026-06-05",
            "symbol_count": 300,
            "trading_day_count": 240,
            "in_sample_end": "2025-12-31",
            "out_sample_start": "2026-01-02",
            "data_version": {
                "csv_dataset_fingerprint": "unit-test-csv-fingerprint",
                "data_source_qa_status": "PASS",
                "data_source_csv_qa_status": "PASS",
                **_source_qa_metadata_with_manifest(root),
            },
        },
    )
    _write_json(
        root / "goal" / "capital_goal_status.json",
        {"decision": "PASS", "blockers": [], "next_actions": ["Continue weekly evidence accumulation."]},
    )
    _write_json(
        root / "goal" / "compounding_path_review.json",
        {
            "decision": "PASS",
            "findings": [],
            "next_actions": ["Continue weekly evidence accumulation."],
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_provider_ramp_report(path: Path, *, status: str) -> None:
    _write_json(
        path,
        {
            "status": status,
            "provider": "akshare",
            "configured_stage_sizes": [2, 20],
            "executed_stage_count": 2,
            "stages": [
                {
                    "index": 1,
                    "size": 2,
                    "status": "PASS",
                    "imported_symbols": 2,
                    "requested_symbols": 2,
                    "bar_rows": 4,
                },
                {
                    "index": 2,
                    "size": 20,
                    "status": status,
                    "imported_symbols": 0 if status == "BLOCK" else 19,
                    "requested_symbols": 20,
                    "bar_rows": 0 if status == "BLOCK" else 38,
                },
            ],
            "research_only": True,
            "source_qa_provenance_status": "NOT_EVALUATED",
            "promotion_gate_effect": "NONE",
            "next_actions": ["Review provider ramp before broad provider imports."],
            "prohibited_actions": [
                "Do not treat AKShare/provider ramp PASS as source QA/provenance PASS."
            ],
        },
    )


def _cfg(cache: Path) -> Config:
    return Config(
        {
            "research": {
                "start": "2024-01-02",
                "end": "2024-01-05",
                "initial_cash": 1_000_000,
                "allow_demo_data": False,
            },
            "data": {"cache_path": str(cache), "source": "csv"},
        }
    )


def _write_config(path: Path, cache: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "research:",
                '  start: "2024-01-02"',
                '  end: "2024-01-05"',
                "  initial_cash: 1000000",
                "  allow_demo_data: false",
                "data:",
                f"  cache_path: '{cache}'",
                "  source: csv",
            ]
        ),
        encoding="utf-8",
    )


def _write_recent_cache(
    cache: Path,
    *,
    with_metadata: bool = True,
    metadata: dict[str, str] | None = None,
) -> None:
    storage = BarStorage(cache)
    days = ["2024-01-02", "2024-01-03", "2024-01-05"]
    storage.save_calendar(days)
    storage.save_stock_info(
        pd.DataFrame(
            {
                "symbol": ["AAA", "BBB"],
                "name": ["Alpha", "Beta"],
            }
        )
    )
    rows = []
    for symbol in ["AAA", "BBB"]:
        for idx, day in enumerate(days):
            price = 10 + idx
            rows.append(
                {
                    "symbol": symbol,
                    "date": day,
                    "open": price,
                    "high": price + 0.5,
                    "low": price - 0.5,
                    "close": price,
                    "volume": 1_000_000,
                    "amount": price * 1_000_000,
                }
            )
    if with_metadata:
        resolved_metadata = dict(
            metadata
            or {
                "csv_dataset_fingerprint": "unit-test-csv-fingerprint",
                "data_source_qa_status": "PASS",
                "data_source_csv_qa_status": "PASS",
                **_source_qa_metadata(cache.parent),
            }
        )
        resolved_metadata.setdefault("data_source", "local_csv")
        storage.save_bars_with_lineage(
            pd.DataFrame(rows),
            source_type="guarded_local_csv",
            source_reference="unit-test-bars.csv",
            source_fingerprint_kind="csv_dataset_fingerprint",
            source_fingerprint=str(resolved_metadata.get("csv_dataset_fingerprint", "")),
            cache_metadata=resolved_metadata,
        )
    else:
        storage.save_bars(pd.DataFrame(rows))
        storage.save_metadata({"data_source": "local_csv"})


def _source_qa_metadata(root: Path) -> dict[str, str]:
    qa_dir = root / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    checklist = qa_dir / "data_source_qa.json"
    answers = qa_dir / "data_source_qa_answers.json"
    if not checklist.exists():
        checklist.write_text('{"checklist": [{"id": "source_identity"}]}', encoding="utf-8")
    if not answers.exists():
        answers.write_text('{"answers": {"source_identity": "yes"}}', encoding="utf-8")
    return {
        "data_source_qa_checklist_path": str(checklist),
        "data_source_qa_checklist_sha256": _sha256(checklist),
        "data_source_qa_answers_path": str(answers),
        "data_source_qa_answers_sha256": _sha256(answers),
    }


def _source_qa_metadata_with_manifest(root: Path) -> dict[str, str]:
    metadata = _source_qa_metadata(root)
    manifest = root / "qa" / "source_qa_evidence_manifest.json"
    if not manifest.exists():
        manifest.write_text('{"evidence": "unit-test"}', encoding="utf-8")
    metadata.update(
        {
            "data_source_qa_evidence_manifest_path": str(manifest),
            "data_source_qa_evidence_manifest_sha256": _sha256(manifest),
        }
    )
    return metadata


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
