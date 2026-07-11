from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from quantify.ops.first_million_daily_brief import (
    build_first_million_daily_brief,
    write_first_million_daily_brief,
)


def test_first_million_daily_brief_rolls_up_operator_focus(tmp_path: Path) -> None:
    _write_blocked_daily_artifacts(tmp_path)

    brief = build_first_million_daily_brief(tmp_path, as_of="2026-06-10")
    out = write_first_million_daily_brief(brief, tmp_path)

    payload = json.loads((out / "first_million_daily_brief.json").read_text(encoding="utf-8"))
    markdown = (out / "first_million_daily_brief.md").read_text(encoding="utf-8")

    assert brief.decision == "BLOCK"
    assert payload["pipeline_decision"] == "BLOCK"
    assert payload["today_focus"]["source"] == "operator_handoff_status"
    assert payload["today_focus"]["task_type"] == "source_qa_worksheet"
    assert payload["today_focus"]["task_count"] == 2
    assert payload["open_task_counts"]["P0"] == 3
    assert payload["top_tasks"][0]["category"] == "source_qa_worksheet"
    assert payload["strategy_goal_gap"]["status"] == "BLOCK"
    assert payload["strategy_goal_gap"]["capital_goal_status"] == "BLOCK"
    assert payload["strategy_goal_gap"]["capital_shortfall"] == 900_000
    assert payload["ranking_status"]["status"] == "MISSING"
    assert payload["ranking_status"]["can_rank_candidates"] is False
    assert "run_strategy_discovery_plan.py" in payload["ranking_status"]["rerun_command"]
    assert any(gate["name"] == "ohlcv_experiment_package" for gate in payload["gate_summary"])
    assert any(gate["name"] == "real_data_batch_onboarding" for gate in payload["gate_summary"])
    assert any(gate["name"] == "evidence_intake_kit" for gate in payload["gate_summary"])
    assert any(gate["name"] == "evidence_work_order" for gate in payload["gate_summary"])
    assert any(gate["name"] == "source_qa_closeout" for gate in payload["gate_summary"])
    assert any(gate["name"] == "data_intake_status" for gate in payload["gate_summary"])
    assert any(gate["name"] == "raw_bars_discovery" for gate in payload["gate_summary"])
    assert any(gate["name"] == "ohlcv_intake_closeout" for gate in payload["gate_summary"])
    assert any(gate["name"] == "market_index_discovery" for gate in payload["gate_summary"])
    assert any(gate["name"] == "market_context_operator_packet" for gate in payload["gate_summary"])
    assert any(gate["name"] == "run_manifest" for gate in payload["gate_summary"])
    assert any(gate["name"] == "micro_live_readiness" for gate in payload["gate_summary"])
    assert any(gate["name"] == "capital_scaling_plan" for gate in payload["gate_summary"])
    assert any("source_identity" in item for item in payload["missing_evidence"])
    assert any("evidence_intake_kit" in item for item in payload["missing_evidence"])
    assert any("evidence_work_order" in item for item in payload["missing_evidence"])
    assert any("source_qa_closeout" in item for item in payload["missing_evidence"])
    assert any("data_intake_status" in item for item in payload["missing_evidence"])
    assert any("source_qa_evidence_inbox_fill" in item for item in payload["missing_evidence"])
    assert any("raw_bars_discovery" in item for item in payload["missing_evidence"])
    assert any("README_raw_bars_dropzone.md" in item for item in payload["missing_evidence"])
    assert any("ohlcv_intake_closeout" in item for item in payload["missing_evidence"])
    assert any("market_index_discovery" in item for item in payload["missing_evidence"])
    assert any("market_context_operator_packet" in item for item in payload["missing_evidence"])
    assert any("ohlcv_experiment_package" in item for item in payload["missing_evidence"])
    assert any("real_data_batch_onboarding" in item for item in payload["missing_evidence"])
    assert any("run_manifest" in item for item in payload["missing_evidence"])
    assert any("strategy_goal_gap" in item for item in payload["missing_evidence"])
    assert any("run_data_source_qa_worksheet_preflight.py" in item for item in payload["commands"])
    assert any(
        "run_source_qa_operator_packet.py" in item and "--write-dropzone-kit" in item
        for item in payload["commands"]
    )
    assert any("run_ohlcv_experiment_package.py" in item for item in payload["commands"])
    assert any("run_real_data_batch_onboarding.py" in item for item in payload["commands"])
    assert any("run_raw_bars_discovery.py" in item for item in payload["commands"])
    assert any("--write-dropzone-kit" in item for item in payload["commands"])
    assert any("run_ohlcv_intake_closeout.py" in item for item in payload["commands"])
    assert any("run_market_index_discovery.py" in item for item in payload["commands"])
    assert any("run_market_context_operator_packet.py" in item for item in payload["commands"])
    assert any("run_strategy_discovery_plan.py" in item for item in payload["commands"])
    assert any("write_data_source_qa_answers.py" in item for item in payload["commands"])
    assert any("run_first_million_evidence_intake_kit.py" in item for item in payload["commands"])
    assert any("run_first_million_evidence_work_order.py" in item for item in payload["commands"])
    assert any("run_source_qa_closeout.py" in item for item in payload["commands"])
    assert any("run_data_intake_status.py" in item for item in payload["commands"])
    assert any("run_market_regime.py" in item for item in payload["commands"])
    assert any("profit claim" in item for item in payload["prohibited_actions"])
    assert "This brief is an operator checklist" in markdown
    assert "## Strategy Goal Gap" in markdown
    assert "## Ranking Status" in markdown
    assert "Capital shortfall: 900,000" in markdown
    assert "Strategy Scope" in markdown


def test_first_million_daily_brief_cli_returns_nonzero_on_block(tmp_path: Path) -> None:
    _write_blocked_daily_artifacts(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_first_million_daily_brief.py",
            "--report-dir",
            str(tmp_path),
            "--as-of",
            "2026-06-10",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((tmp_path / "first_million_daily_brief.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"
    assert payload["today_focus"]["task_type"] == "source_qa_worksheet"


def test_first_million_daily_brief_keeps_inbox_placeholder_args_blocked(tmp_path: Path) -> None:
    _write_blocked_daily_artifacts(tmp_path)
    _write_json(
        tmp_path / "source_qa_evidence_inbox.json",
        {
            "status": "BLOCK",
            "required_item_count": 2,
            "matched_item_count": 1,
            "missing_item_count": 1,
            "invalid_file_count": 0,
            "scanned_file_count": 1,
            "worksheet_fill_args": [
                {
                    "item_id": "source_identity",
                    "cli_argument": "--source-identity-evidence",
                    "value": "data_exports\\source_qa_evidence\\source_identity_receipt.png",
                    "source": "target_path",
                    "exists": True,
                    "status": "BLOCK",
                    "message": "Human placeholder target_path; add a matched local evidence file before use.",
                }
            ],
            "items": [],
            "unmatched_files": [],
            "next_actions": [
                "source_identity --source-identity-evidence is a human placeholder, not ready."
            ],
            "next_commands": [
                ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_evidence_inbox.py --data-dir data_exports --report-dir results\\first_million"
            ],
        },
    )
    _write_json(
        tmp_path / "data_intake_status.json",
        {
            "decision": "PASS",
            "next_area": "",
            "next_action": "All intake status items are PASS.",
            "summary": {
                "raw_bars_status": "PASS",
                "source_evidence_status": "PASS",
                "worksheet_fill_ready": True,
            },
            "items": [],
            "command_sequence": [],
        },
    )

    brief = build_first_million_daily_brief(tmp_path, as_of="2026-06-10")
    payload = brief.to_dict()
    gates = {gate["name"]: gate for gate in payload["gate_summary"]}

    assert payload["decision"] == "BLOCK"
    assert gates["source_qa_evidence_inbox"]["status"] == "BLOCK"
    assert "human placeholder" in gates["source_qa_evidence_inbox"]["summary"]
    assert any("human placeholder" in item for item in payload["missing_evidence"])
    assert any("run_source_qa_evidence_inbox.py" in item for item in payload["commands"])


def test_first_million_daily_brief_passes_only_when_underlying_artifacts_pass(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "first_million_pipeline.json", {"decision": "PASS", "stages": []})
    _write_json(
        tmp_path / "operator_handoff_status.json",
        {
            "status": "PASS",
            "open_task_count": 0,
            "p0_open_task_count": 0,
            "p1_open_task_count": 0,
            "next_batch": {"task_count": 0},
        },
    )
    _write_json(
        tmp_path / "source_qa" / "source_qa_evidence_readiness.json",
        {"status": "PASS", "sections": []},
    )
    _write_json(
        tmp_path / "source_qa_evidence_inbox.json",
        {
            "status": "PASS",
            "required_item_count": 5,
            "matched_item_count": 5,
            "missing_item_count": 0,
            "invalid_file_count": 0,
            "scanned_file_count": 5,
            "worksheet_fill_command_ready": True,
            "worksheet_fill_command_status": "PASS",
            "worksheet_fill_command_blockers": [],
            "worksheet_fill_command_warnings": [],
            "items": [],
            "unmatched_files": [],
            "next_actions": [],
            "next_commands": [],
        },
    )
    _write_json(
        tmp_path / "source_qa_closeout.json",
        {
            "decision": "PASS",
            "allowed_next_stage": "GUARDED_OFFLINE_INTAKE",
            "counts": {
                "open_action_count": 0,
                "missing_worksheet_count": 0,
                "missing_attachment_count": 0,
            },
            "actions": [],
            "command_sequence": [],
            "capability_flags": {
                "can_enter_paper": False,
                "can_enter_live": False,
                "can_generate_broker_orders": False,
            },
        },
    )
    _write_json(
        tmp_path / "data_intake_status.json",
        {
            "decision": "PASS",
            "next_area": "",
            "next_action": "All intake status items are PASS.",
            "summary": {
                "raw_bars_status": "PASS",
                "source_evidence_status": "PASS",
                "worksheet_fill_ready": True,
            },
            "items": [],
            "command_sequence": [],
        },
    )
    _write_json(
        tmp_path / "evidence_intake_kit" / "first_million_evidence_intake_kit.json",
        {
            "decision": "PASS",
            "file_count": 0,
            "kit_dir": str(tmp_path / "evidence_intake_kit"),
            "files": [],
            "command_sequence": [],
            "next_actions": [],
        },
    )
    _write_json(
        tmp_path / "first_million_evidence_work_order.json",
        {
            "decision": "PASS",
            "next_batch_id": "",
            "open_batch_count": 0,
            "batches": [],
            "command_sequence": [],
        },
    )
    _write_json(
        tmp_path / "raw_bars_discovery.json",
        {
            "status": "PASS",
            "best_candidate": "raw.csv",
            "candidates": [{"message": "Normalizable raw bars CSV."}],
        },
    )
    _write_json(
        tmp_path / "ohlcv_intake_closeout.json",
        {
            "decision": "PASS",
            "source_qa_status": "PASS",
            "raw_discovery_status": "PASS",
            "offline_intake_status": "PASS",
            "latest_bar_date": "2024-01-03",
            "blockers": [],
            "watch_items": [],
            "next_actions": [],
            "command_sequence": [],
        },
    )
    _write_json(
        tmp_path / "market_context_readiness.json",
        {
            "decision": "PASS",
            "source": "market_regime",
            "label": "neutral",
            "blockers": [],
            "watch_items": [],
        },
    )
    _write_json(
        tmp_path / "market_index_discovery.json",
        {
            "status": "PASS",
            "best_candidate": "data_exports\\indices\\indices.csv",
            "candidates": [
                {
                    "path": "data_exports\\indices\\indices.csv",
                    "status": "PASS",
                    "index_count": 1,
                    "findings": [],
                }
            ],
            "next_commands": [],
        },
    )
    _write_json(
        tmp_path / "market_context_operator_packet.json",
        {
            "decision": "PASS",
            "readiness_source": "market_regime",
            "readiness_decision": "PASS",
            "readiness_label": "neutral",
            "missing_item_count": 0,
            "items": [],
        },
    )
    _write_json(
        tmp_path / "ohlcv_experiment_package.json",
        {
            "decision": "PASS",
            "launch_research_allowed": True,
            "bars": {"state": "present", "symbol_count": 300, "trading_day_count": 240},
            "blockers": [],
            "watch_items": [],
        },
    )
    _write_json(
        tmp_path / "real_data_batch_onboarding.json",
        {
            "decision": "PASS",
            "steps": [],
            "blockers": [],
            "watch_items": [],
        },
    )
    _write_json(
        tmp_path / "candidate_experiment_readiness.json",
        {
            "decision": "PASS",
            "runnable_count": 1,
            "blocked_count": 0,
            "scope_summary": {"OHLCV_ONLY": {"total": 1, "ready": 1, "blocked": 0}},
        },
    )
    _write_json(
        tmp_path / "run_manifest.json",
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
            },
        },
    )
    _write_json(
        tmp_path / "first_million_resolution_plan.json",
        {
            "decision": "PASS",
            "as_of": "2026-06-10",
            "task_counts": {"total": 0, "P0": 0, "P1": 0, "P2": 0},
            "tasks": [],
        },
    )
    _write_json(tmp_path / "first_million_readiness.json", {"decision": "PASS", "gates": []})
    _write_json(
        tmp_path / "first_million_strategy_brief.json",
        {
            "decision": "RUN_RESEARCH",
            "top_research_candidate": "price_volume_defensive",
            "compounding_goal": {
                "status": "PASS",
                "selected_candidate": "price_volume_defensive",
                "top_candidate": "price_volume_defensive",
                "candidate_selection_status": "PASS",
                "capital_goal_status": "PASS",
                "compounding_path_decision": "PASS",
                "required_annual_return": 0.333,
                "projected_capital_at_horizon": 1_100_000,
                "capital_shortfall": 0,
                "gap_items": [],
                "can_claim_compounding_path": True,
            },
        },
    )

    brief = build_first_million_daily_brief(tmp_path, as_of="2026-06-10")

    assert brief.decision == "PASS"
    assert brief.strategy_goal_gap["status"] == "PASS"
    assert brief.ranking_status.status == "MISSING"
    assert brief.ranking_status.can_rank_candidates is False
    assert all("strategy_ranking" not in item for item in brief.missing_evidence)
    assert brief.today_focus["task_type"] == "review"
    assert "manual approval" in brief.today_focus["target"]
    assert brief.research_focus["artifact_type"] == "recent_candidate_research"
    assert any(gate.name == "run_manifest" and gate.status == "PASS" for gate in brief.gate_summary)
    assert any(gate.name == "data_intake_status" and gate.status == "PASS" for gate in brief.gate_summary)
    assert any("real broker" in item for item in brief.prohibited_actions)
    assert "## Ranking Status" in brief.to_markdown()


def test_first_million_daily_brief_surfaces_downstream_gate_blocks(tmp_path: Path) -> None:
    _write_blocked_daily_artifacts(tmp_path)
    _write_json(
        tmp_path / "run_manifest.json",
        {
            "demo_data_used": False,
            "in_sample_end": "2025-12-31",
            "out_sample_start": "2026-01-02",
            "data_version": {
                "csv_dataset_fingerprint": "unit-test-csv-fingerprint",
                "data_source_qa_status": "PASS",
                "data_source_csv_qa_status": "PASS",
            },
        },
    )
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
            "blockers": ["RUN_MANIFEST: missing source QA evidence manifest."],
        },
    )

    brief = build_first_million_daily_brief(tmp_path, as_of="2026-06-10")
    payload = brief.to_dict()
    gates = {gate["name"]: gate for gate in payload["gate_summary"]}

    assert payload["decision"] == "BLOCK"
    assert gates["micro_live_readiness"]["status"] == "BLOCK"
    assert "MISSING_APPROVAL" in gates["micro_live_readiness"]["summary"]
    assert gates["capital_scaling_plan"]["status"] == "BLOCK"
    assert "RUN_MANIFEST" in gates["capital_scaling_plan"]["summary"]
    assert any("micro_live_readiness" in item for item in payload["missing_evidence"])
    assert any("Micro-live readiness is BLOCK" in item for item in payload["blocked_strategy_scope"])
    assert any("Capital scaling plan is BLOCK" in item for item in payload["blocked_strategy_scope"])


def test_first_million_daily_brief_surfaces_strategy_ranking_gate(tmp_path: Path) -> None:
    _write_blocked_daily_artifacts(tmp_path)
    _write_json(
        tmp_path / "strategy_discovery_plan.json",
        {
            "decision": "PREPARE_DATA",
            "status": "BLOCK",
            "top_candidate": "price_volume_defensive",
            "top_candidate_basis": "pre_registered_priority_without_ranking",
            "can_rank_candidates": False,
            "ranking_gate": {
                "status": "BLOCK",
                "can_rank_candidates": False,
                "basis": "pre-registered candidate priority only; formal ranking is disabled",
                "candidate_selection_status": "MISSING",
                "ranked_candidate_count": 0,
                "top_ranked_candidate": "",
                "blocked_by": [
                    "candidate_selection.json is missing; no deterministic ranking report exists."
                ],
            },
        },
    )

    brief = build_first_million_daily_brief(tmp_path, as_of="2026-06-10")
    out = write_first_million_daily_brief(brief, tmp_path)
    payload = json.loads((out / "first_million_daily_brief.json").read_text(encoding="utf-8"))
    markdown = (out / "first_million_daily_brief.md").read_text(encoding="utf-8")
    gates = {gate["name"]: gate for gate in payload["gate_summary"]}

    assert payload["ranking_status"]["status"] == "BLOCK"
    assert payload["ranking_status"]["can_rank_candidates"] is False
    assert payload["ranking_status"]["top_candidate"] == "price_volume_defensive"
    assert payload["ranking_status"]["top_candidate_basis"] == "pre_registered_priority_without_ranking"
    assert payload["ranking_status"]["candidate_selection_status"] == "MISSING"
    assert "candidate_selection.json is missing" in payload["ranking_status"]["first_blocker"]
    assert gates["strategy_discovery_plan"]["status"] == "BLOCK"
    assert "can_rank=false" in gates["strategy_discovery_plan"]["summary"]
    assert any("strategy_ranking" in item for item in payload["missing_evidence"])
    assert any("Formal strategy ranking is disabled" in item for item in payload["blocked_strategy_scope"])
    assert "Top candidate basis: `pre_registered_priority_without_ranking`" in markdown
    assert "formal candidate ranking is disabled" in markdown


def test_first_million_daily_brief_surfaces_recent_research_focus(tmp_path: Path) -> None:
    _write_blocked_daily_artifacts(tmp_path)
    recent_dir = tmp_path / "research_recent"
    _write_recent_candidate_run(
        recent_dir / "20260618_010000_defensive_cash_guard",
        candidate="defensive_cash_guard_price_volume",
    )

    brief = build_first_million_daily_brief(
        tmp_path,
        as_of="2026-06-18",
        recent_research_dir=recent_dir,
    )
    payload = brief.to_dict()

    assert payload["research_focus"]["artifact_type"] == "recent_candidate_research"
    assert payload["research_focus"]["best_research_candidate"] == "defensive_cash_guard_price_volume"
    assert any(gate.name == "recent_candidate_research" for gate in brief.gate_summary)
    assert any("Recent research focus is defensive_cash_guard_price_volume" in item for item in brief.blocked_strategy_scope)
    assert brief.research_focus["best_research_command"].endswith(
        "--candidate defensive_cash_guard_price_volume"
    )


def test_first_million_daily_brief_prefers_latest_real_candidate_research_dir(tmp_path: Path) -> None:
    _write_blocked_daily_artifacts(tmp_path)
    older_dir = tmp_path / "research_recent"
    newer_dir = tmp_path / "research_recent_real_candidates"
    _write_recent_candidate_run(
        older_dir / "20260618_010000_defensive_cash_guard",
        candidate="defensive_cash_guard_price_volume",
    )
    _write_recent_candidate_run(
        newer_dir / "20260618_new_variants_precheck",
        candidate="trend_filtered_quarterly_price_volume",
    )

    brief = build_first_million_daily_brief(tmp_path, as_of="2026-06-18")

    assert brief.research_focus["search_dir"].endswith("research_recent_real_candidates")
    assert brief.research_focus["best_research_candidate"] == "trend_filtered_quarterly_price_volume"
    assert any(
        "run_recent_candidate_research.py --search-dir" in command
        and "research_recent_real_candidates" in command
        for command in brief.commands
    )


def _write_blocked_daily_artifacts(root: Path) -> None:
    _write_json(
        root / "first_million_pipeline.json",
        {
            "decision": "BLOCK",
            "stages": [
                {
                    "name": "source_qa_preflight",
                    "status": "BLOCK",
                    "artifact": str(root / "source_qa" / "source_qa_preflight.json"),
                    "message": "Source QA answers are missing.",
                },
                {
                    "name": "weekly_pipeline",
                    "status": "SKIPPED",
                    "artifact": str(root / "weekly" / "weekly_pipeline.json"),
                    "message": "Skipped until source QA passes.",
                },
            ],
        },
    )
    _write_json(
        root / "operator_handoff_status.json",
        {
            "status": "BLOCK",
            "open_task_count": 3,
            "p0_open_task_count": 3,
            "p1_open_task_count": 0,
            "source_qa_open_task_count": 2,
            "source_qa_attachment_open_task_count": 1,
            "data_export_open_task_count": 0,
            "next_batch": {
                "status": "BLOCK",
                "priority": "P0",
                "task_type": "source_qa_worksheet",
                "task_count": 2,
                "source_artifacts": ["source_qa_worksheet_todo.csv"],
                "acceptance_criteria": "Worksheet rows are filled from retained evidence.",
                "next_command": (
                    ".\\.venv\\Scripts\\python.exe "
                    "examples\\run_data_source_qa_worksheet_preflight.py "
                    "--checklist data_exports\\data_source_qa.json "
                    "--worksheet data_exports\\data_source_qa_evidence_worksheet.csv "
                    "--output-dir data_exports"
                ),
                "sample_tasks": [
                    {
                        "item": "row 2: data_vendor_or_broker",
                        "target": "data_exports\\data_source_qa_evidence_worksheet.csv",
                    },
                    {
                        "item": "row 10: source_identity",
                        "target": "data_exports\\data_source_qa_evidence_worksheet.csv",
                    },
                ],
            },
        },
    )
    _write_json(
        root / "source_qa" / "source_qa_evidence_readiness.json",
        {
            "status": "BLOCK",
            "sections": [
                {
                    "name": "worksheet_preflight",
                    "status": "BLOCK",
                    "blockers": ["source_identity: retained evidence note is missing."],
                },
                {
                    "name": "manifest_preflight",
                    "status": "BLOCK",
                    "blockers": ["license_scope: attachment is missing."],
                },
            ],
            "next_commands": [
                ".\\.venv\\Scripts\\python.exe "
                "examples\\run_data_source_qa_worksheet_preflight.py "
                "--checklist data_exports\\data_source_qa.json "
                "--worksheet data_exports\\data_source_qa_evidence_worksheet.csv "
                "--output-dir data_exports"
            ],
        },
    )
    _write_json(
        root / "source_qa_evidence_inbox.json",
        {
            "status": "BLOCK",
            "required_item_count": 5,
            "matched_item_count": 0,
            "missing_item_count": 5,
            "invalid_file_count": 0,
            "scanned_file_count": 0,
            "worksheet_fill_command": (
                ".\\.venv\\Scripts\\python.exe examples\\fill_data_source_qa_evidence_worksheet.py "
                "--source-identity-evidence data_exports\\source_qa_evidence\\source_identity_receipt.png"
            ),
            "worksheet_fill_command_ready": False,
            "worksheet_fill_command_status": "BLOCK",
            "worksheet_fill_command_blockers": [
                "source_identity: target_path value is not ready evidence for --source-identity-evidence."
            ],
            "worksheet_fill_command_warnings": [],
            "items": [
                {
                    "item_id": "source_identity",
                    "status": "BLOCK",
                    "message": "Required source QA evidence attachment is missing from the inbox.",
                }
            ],
            "unmatched_files": [],
            "next_actions": ["Add retained local evidence files for missing source QA ids: source_identity."],
            "next_commands": [
                ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_evidence_inbox.py --data-dir data_exports --report-dir results\\first_million"
            ],
        },
    )
    _write_json(
        root / "data_intake_status.json",
        {
            "decision": "BLOCK",
            "next_area": "operator_next_batch",
            "next_action": "Fill source QA worksheet rows from retained evidence.",
            "next_command": (
                ".\\.venv\\Scripts\\python.exe examples\\run_data_intake_status.py "
                "--report-dir results\\first_million --data-dir data_exports --as-of 2026-06-10"
            ),
            "summary": {
                "raw_bars_status": "BLOCK",
                "source_evidence_status": "BLOCK",
                "worksheet_fill_ready": False,
            },
            "items": [
                {
                    "area": "operator_next_batch",
                    "status": "BLOCK",
                    "next_action": "Fill source QA worksheet rows from retained evidence.",
                }
            ],
            "command_sequence": [],
        },
    )
    _write_json(
        root / "source_qa_closeout.json",
        {
            "decision": "BLOCK",
            "allowed_next_stage": "COLLECT_EVIDENCE",
            "counts": {
                "open_action_count": 3,
                "missing_worksheet_count": 2,
                "missing_attachment_count": 1,
            },
            "next_action": (
                "Start with `source_qa_worksheet/data_vendor_or_broker`: "
                "Fill the worksheet row from retained vendor/export evidence."
            ),
            "actions": [
                {
                    "status": "BLOCK",
                    "category": "source_qa_worksheet",
                    "item": "data_vendor_or_broker",
                    "action": "Fill the worksheet row from retained vendor/export evidence.",
                }
            ],
            "command_sequence": [
                ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_closeout.py --data-dir data_exports --report-dir results\\first_million"
            ],
            "capability_flags": {
                "can_enter_paper": False,
                "can_enter_live": False,
                "can_generate_broker_orders": False,
            },
        },
    )
    _write_json(
        root / "evidence_intake_kit" / "first_million_evidence_intake_kit.json",
        {
            "decision": "BLOCK",
            "file_count": 2,
            "kit_dir": str(root / "evidence_intake_kit"),
            "files": [
                {
                    "item_type": "source_qa_attachment",
                    "item_id": "source_identity",
                    "target_path": "data_exports\\source_qa_evidence\\source_identity_receipt.png",
                }
            ],
            "command_sequence": [
                ".\\.venv\\Scripts\\python.exe examples\\run_first_million_evidence_intake_kit.py --report-dir results\\first_million --data-dir data_exports --as-of 2026-06-10"
            ],
        },
    )
    _write_json(
        root / "first_million_evidence_work_order.json",
        {
            "decision": "BLOCK",
            "next_batch_id": "source_qa_worksheet",
            "open_batch_count": 3,
            "batches": [
                {
                    "batch_id": "source_qa_worksheet",
                    "status": "BLOCK",
                    "title": "Fill source QA worksheet rows from retained evidence.",
                }
            ],
            "command_sequence": [
                ".\\.venv\\Scripts\\python.exe examples\\run_first_million_evidence_work_order.py --report-dir results\\first_million --data-dir data_exports --as-of 2026-06-10"
            ],
        },
    )
    _write_json(
        root / "raw_bars_discovery.json",
        {
            "status": "BLOCK",
            "best_candidate": "",
            "candidates": [{"message": "No candidate raw bars CSV files were found."}],
            "dropzone_kit": {
                "dropzone_dir": "data_exports\\raw",
                "readme_path": "data_exports\\raw\\README_raw_bars_dropzone.md",
            },
            "next_commands": [
                ".\\.venv\\Scripts\\python.exe examples\\run_raw_bars_discovery.py --search-dir <raw-bars-directory>"
            ],
        },
    )
    _write_json(
        root / "ohlcv_intake_closeout.json",
        {
            "decision": "BLOCK",
            "source_qa_status": "BLOCK",
            "raw_discovery_status": "PASS",
            "offline_intake_status": "NOT_RUN",
            "latest_bar_date": "",
            "blockers": ["source_qa: data_source_qa_answers.json is missing."],
            "watch_items": [],
            "next_actions": ["Fix source QA before guarded intake."],
            "command_sequence": [
                ".\\.venv\\Scripts\\python.exe examples\\run_ohlcv_intake_closeout.py --data-dir data_exports --report-dir results\\first_million"
            ],
        },
    )
    _write_json(
        root / "market_context_readiness.json",
        {
            "decision": "BLOCK",
            "source": "missing",
            "label": "unknown",
            "blockers": ["market_context=MISSING: provide market_regime.json."],
            "watch_items": [],
        },
    )
    _write_json(
        root / "market_index_discovery.json",
        {
            "status": "BLOCK",
            "best_candidate": "",
            "candidates": [{"findings": ["No candidate index CSV files were found."]}],
            "next_commands": [
                ".\\.venv\\Scripts\\python.exe examples\\run_market_index_discovery.py --search-dir data_exports\\indices --output-dir results\\first_million --as-of 2026-06-10"
            ],
        },
    )
    _write_json(
        root / "market_context_operator_packet.json",
        {
            "decision": "BLOCK",
            "readiness_source": "missing",
            "readiness_decision": "BLOCK",
            "readiness_label": "unknown",
            "missing_item_count": 2,
            "items": [
                {
                    "item_type": "preferred_artifact",
                    "item_id": "market_regime",
                    "required_value": "Generate cache-derived market_regime.json.",
                },
                {
                    "item_type": "snapshot_metadata",
                    "item_id": "as_of",
                    "required_value": "Record snapshot date.",
                },
            ],
            "command_sequence": [
                ".\\.venv\\Scripts\\python.exe examples\\run_market_context_operator_packet.py --report-dir results\\first_million --as-of 2026-06-10"
            ],
        },
    )
    _write_json(
        root / "ohlcv_experiment_package.json",
        {
            "decision": "BLOCK",
            "launch_research_allowed": False,
            "bars": {"state": "template_sample_rows", "symbol_count": 2, "trading_day_count": 2},
            "blockers": [
                "bars_csv: bars.csv state is template_sample_rows; real non-template OHLCV rows are required."
            ],
            "watch_items": [],
        },
    )
    _write_json(
        root / "real_data_batch_onboarding.json",
        {
            "decision": "BLOCK",
            "steps": [
                {
                    "name": "raw_bars_csv",
                    "status": "BLOCK",
                    "message": "No raw broker/vendor bars CSV path was supplied.",
                }
            ],
            "blockers": ["raw_bars_csv: No raw broker/vendor bars CSV path was supplied."],
            "watch_items": [],
        },
    )
    _write_json(
        root / "candidate_experiment_readiness.json",
        {
            "decision": "BLOCK",
            "runnable_count": 0,
            "blocked_count": 6,
            "blockers": ["source_qa_preflight=BLOCK"],
            "scope_summary": {
                "OHLCV_ONLY": {
                    "total": 1,
                    "ready": 0,
                    "blocked": 1,
                    "note": "OHLCV path is not ready.",
                }
            },
        },
    )
    _write_json(
        root / "first_million_resolution_plan.json",
        {
            "decision": "BLOCK",
            "as_of": "2026-06-10",
            "pipeline_decision": "BLOCK",
            "task_counts": {
                "total": 4,
                "P0": 3,
                "P1": 1,
                "P2": 0,
                "open": 4,
                "waiting": 0,
                "watch": 0,
            },
            "tasks": [
                {
                    "priority": "P0",
                    "status": "OPEN",
                    "category": "source_qa_worksheet",
                    "item": "row 2: data_vendor_or_broker",
                    "target": "data_exports\\data_source_qa_evidence_worksheet.csv",
                    "action": "Required source metadata answer is missing.",
                    "acceptance_criteria": "Fill worksheet row from real export evidence.",
                    "command": (
                        ".\\.venv\\Scripts\\python.exe "
                        "examples\\run_data_source_qa_worksheet_preflight.py "
                        "--checklist data_exports\\data_source_qa.json "
                        "--worksheet data_exports\\data_source_qa_evidence_worksheet.csv "
                        "--output-dir data_exports"
                    ),
                    "source_artifact": "source_qa_worksheet_todo.csv",
                },
                {
                    "priority": "P0",
                    "status": "OPEN",
                    "category": "source_qa_attachment",
                    "item": "source_identity",
                    "target": "data_exports\\source_qa_evidence\\source_identity.txt",
                    "action": "Attach retained source identity evidence.",
                    "acceptance_criteria": "Attachment is included in strict manifest.",
                    "command": (
                        ".\\.venv\\Scripts\\python.exe "
                        "examples\\write_source_qa_evidence_manifest.py "
                        "--checklist data_exports\\data_source_qa.json "
                        "--evidence-dir data_exports\\source_qa_evidence "
                        "--output-dir data_exports --strict"
                    ),
                    "source_artifact": "source_qa_attachment_todo.csv",
                },
            ],
        },
    )
    _write_json(
        root / "first_million_readiness.json",
        {"decision": "BLOCK", "blockers": ["current_data_cache is BLOCK."], "gates": []},
    )
    _write_json(
        root / "first_million_strategy_brief.json",
        {
            "decision": "PREPARE_DATA",
            "top_research_candidate": "price_volume_defensive",
            "compounding_goal": {
                "status": "BLOCK",
                "selected_candidate": "",
                "top_candidate": "price_volume_defensive",
                "candidate_selection_status": "MISSING",
                "capital_goal_status": "BLOCK",
                "compounding_path_decision": "BLOCK",
                "required_annual_return": 0.3335,
                "projected_capital_at_horizon": 100_000,
                "capital_shortfall": 900_000,
                "gap_items": [
                    "candidate_selection.json is missing; no strategy can be tied to the one-million path.",
                    "capital_goal_status blocker: current cache is not ready.",
                    "compounding_path BLOCK HUMAN_APPROVAL_MISSING.",
                ],
                "can_claim_compounding_path": False,
            },
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_recent_candidate_run(report_dir: Path, *, candidate: str) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        report_dir / "candidate_selection.json",
        {
            "status": "BLOCK",
            "top_candidate": candidate,
            "selected_candidate": "",
            "results": [
                {
                    "name": candidate,
                    "score": {"decision": "BLOCK", "score": 0.0},
                    "metrics": {
                        "annualized_return": -0.1196,
                        "max_drawdown": 0.0559,
                        "sharpe_ratio": -1.33,
                    },
                    "avg_turnover_pct": 0.8688,
                    "reject_rate": 0.0,
                    "capital_goal_fit_review": {
                        "status": "BLOCK",
                        "return_margin": -0.4531,
                        "findings": ["Annual return is below required path."],
                    },
                }
            ],
        },
    )
    _write_json(
        report_dir / "candidate_research_precheck.json",
        {
            "status": "RESEARCH_ONLY",
            "promotion_decision": "BLOCK",
            "candidates": [candidate],
            "missing_promotion_evidence": [
                "PASS source QA, guarded offline intake, data audit, and run manifest evidence."
            ],
        },
    )
    _write_json(
        report_dir / "candidate_walk_forward_report.json",
        {
            "status": "WATCH",
            "summaries": [
                {
                    "candidate": candidate,
                    "status": "WATCH",
                    "window_count": 3,
                    "positive_return_ratio": 0.3333,
                    "worst_total_return": -0.0294,
                    "worst_max_drawdown": 0.0559,
                }
            ],
        },
    )
    _write_json(
        report_dir / "candidate_factor_diagnostics.json",
        {
            "status": "WATCH",
            "diagnostics": [
                {
                    "candidate": candidate,
                    "status": "WATCH",
                    "component_count": 3,
                    "component_pass_count": 0,
                    "dependency_ratio": 0.0,
                    "findings": ["WATCH: component PASS ratio 0% is below 40%."],
                }
            ],
        },
    )
    _write_json(
        report_dir / "candidate_regime_validation_report.json",
        {
            "status": "WATCH",
            "summaries": [
                {
                    "candidate": candidate,
                    "status": "WATCH",
                    "known_regime_count": 2,
                    "adverse_regime_window_count": 2,
                    "block_bucket_count": 0,
                    "notes": ["Regime-stratified validation is watch-only."],
                }
            ],
        },
    )
    _write_json(
        report_dir / "candidate_stress_matrix.json",
        {
            "status": "RESEARCH_ONLY",
            "promotion_decision": "BLOCK",
            "summaries": [
                {
                    "candidate": candidate,
                    "status": "WATCH",
                    "scenario_count": 6,
                    "pass_count": 0,
                    "watch_count": 6,
                    "block_count": 0,
                    "worst_total_return": -0.0493,
                    "worst_max_drawdown": 0.0675,
                    "max_turnover_pct": 0.8904,
                    "findings": ["No stress scenario reached PASS."],
                }
            ],
        },
    )
