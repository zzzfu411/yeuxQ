from __future__ import annotations

import json
from pathlib import Path
import csv
import struct
import subprocess
import sys

import pandas as pd

from quantify.data.csv_contract import write_research_csv_templates
from quantify.data.storage import BarStorage
import quantify.ops.first_million as first_million_module
from quantify.ops.first_million import FirstMillionPipelineStage, run_first_million_pipeline
from quantify.data.source_qa import (
    build_data_source_qa,
    build_data_source_qa_answers,
    build_data_source_qa_evidence_worksheet,
    build_source_qa_evidence_manifest,
    write_data_source_qa,
    write_data_source_qa_answers,
    write_source_qa_evidence_manifest,
)
from quantify.research.candidate_experiment_execution import (
    CandidateExperimentExecutionReport,
    CandidateExperimentExecutionStep,
)
from quantify.research.candidate_experiment_queue import build_candidate_experiment_queue
from quantify.research.candidate_experiment_readiness import build_candidate_experiment_readiness
from quantify.research.candidate_hypotheses import build_candidate_hypothesis_catalog


def test_first_million_pipeline_blocks_missing_source_qa_answers(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        registry_path=None,
    )

    assert result.decision == "BLOCK"
    assert (output / "first_million_pipeline.json").exists()
    assert (output / "candidate_hypotheses.json").exists()
    assert (output / "candidate_experiment_queue.json").exists()
    assert (output / "candidate_experiment_design_matrix.json").exists()
    assert (output / "candidate_experiment_design_matrix.md").exists()
    assert (output / "candidate_experiment_design_matrix.csv").exists()
    assert (output / "candidate_experiment_readiness.json").exists()
    assert (output / "candidate_experiment_readiness_matrix.csv").exists()
    assert (output / "first_million_strategy_brief.json").exists()
    assert (output / "candidate_experiment_launch.json").exists()
    assert (output / "candidate_experiment_run_packet.json").exists()
    assert (output / "candidate_experiment_run_packet.md").exists()
    assert (output / "candidate_experiment_run_packet.csv").exists()
    assert (output / "candidate_experiment_execution.json").exists()
    assert (output / "candidate_experiment_completion.json").exists()
    assert (output / "first_million_readiness.json").exists()
    assert (output / "recent_data_acquisition_plan.json").exists()
    assert (output / "provider_smoke_readiness.json").exists()
    assert (output / "provider_smoke_readiness.md").exists()
    assert (output / "data_gap_action_plan.json").exists()
    assert (output / "data_evidence_action_packet.json").exists()
    assert (output / "source_qa_operator_packet.json").exists()
    assert (output / "source_qa_operator_packet.md").exists()
    assert (output / "source_qa_operator_packet.csv").exists()
    assert (data_dir / "source_qa_evidence" / "README_source_qa_evidence_dropzone.md").exists()
    assert (output / "source_qa_closeout.json").exists()
    assert (output / "source_qa_closeout.md").exists()
    assert (output / "source_qa_closeout.csv").exists()
    assert (output / "evidence_intake_kit" / "first_million_evidence_intake_kit.json").exists()
    assert (output / "evidence_intake_kit" / "first_million_evidence_intake_manifest.csv").exists()
    assert (output / "first_million_evidence_work_order.json").exists()
    assert (output / "first_million_evidence_work_order.md").exists()
    assert (output / "first_million_evidence_work_order.csv").exists()
    assert (output / "raw_bars_discovery.json").exists()
    assert (output / "raw_bars_discovery.md").exists()
    assert (output / "ohlcv_intake_closeout.json").exists()
    assert (output / "ohlcv_intake_closeout.md").exists()
    assert (output / "ohlcv_intake_closeout.csv").exists()
    assert (output / "data_intake_status.json").exists()
    assert (output / "data_intake_status.md").exists()
    assert (output / "data_intake_status.csv").exists()
    assert (output / "market_index_discovery.json").exists()
    assert (output / "market_index_discovery.md").exists()
    assert (output / "market_context_operator_packet.json").exists()
    assert (output / "market_context_operator_packet.md").exists()
    assert (output / "market_context_operator_packet.csv").exists()
    assert (output / "operator_handoff.csv").exists()
    assert (output / "operator_handoff.md").exists()
    assert (output / "operator_handoff_status.json").exists()
    assert (output / "operator_handoff_status.md").exists()
    assert (output / "first_million_resolution_plan.json").exists()
    assert (output / "first_million_resolution_plan.md").exists()
    assert (output / "first_million_resolution_plan.csv").exists()
    assert (output / "first_million_daily_brief.json").exists()
    assert (output / "first_million_daily_brief.md").exists()
    assert (output / "strategy_discovery_plan.json").exists()
    assert (output / "strategy_discovery_plan.md").exists()
    assert (output / "strategy_discovery_plan.csv").exists()
    assert (output / "first_million_evidence_ranking_dashboard.json").exists()
    assert (output / "first_million_evidence_ranking_dashboard.md").exists()
    assert (output / "first_million_evidence_ranking_dashboard.csv").exists()
    assert (output / "ohlcv_experiment_package.json").exists()
    assert (output / "ohlcv_experiment_package.md").exists()
    assert (output / "ohlcv_experiment_package.csv").exists()
    assert (output / "real_data_batch_onboarding.json").exists()
    assert (output / "real_data_batch_onboarding.md").exists()
    assert (output / "real_data_batch_onboarding.csv").exists()
    assert (output / "csv_intake_preview.json").exists()
    assert (output / "csv_intake_preview.md").exists()
    assert (output / "data_intake_router.json").exists()
    assert (output / "tdx_day_discovery.json").exists()
    assert (output / "offline_data_package.json").exists()
    assert (output / "real_data_handoff_checklist.json").exists()
    assert (output / "source_qa" / "source_qa_preflight.json").exists()
    assert (output / "source_qa" / "data_source_qa_review.json").exists()
    assert (output / "source_qa" / "source_qa_evidence_readiness.json").exists()
    assert (output / "offline_intake" / "offline_data_intake.json").exists()
    assert (output / "promotion_metadata_check.json").exists()
    assert (output / "promotion_metadata_check.md").exists()
    assert (output / "goal" / "capital_goal_status.json").exists()
    assert (output / "goal" / "compounding_path_review.json").exists()
    assert not (output / "weekly" / "weekly_pipeline.json").exists()
    assert not (output / "weekly" / "weekly_pipeline.json").exists()
    assert any(stage.name == "candidate_hypotheses" and stage.status == "PASS" for stage in result.stages)
    assert any(stage.name == "data_gap_action_plan" and stage.status == "BLOCK" for stage in result.stages)
    assert any(
        stage.name == "data_evidence_action_packet" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(stage.name == "ohlcv_intake_closeout" and stage.status == "BLOCK" for stage in result.stages)
    assert any(
        stage.name == "operator_handoff_status" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(
        stage.name == "raw_bars_discovery" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(
        stage.name == "source_qa_evidence_readiness" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(stage.name == "source_qa_closeout" and stage.status == "BLOCK" for stage in result.stages)
    assert any(stage.name == "data_intake_status" and stage.status == "BLOCK" for stage in result.stages)
    assert any(stage.name == "csv_intake_preview" and stage.status == "PASS" for stage in result.stages)
    assert any(stage.name == "data_intake_router" and stage.status == "BLOCK" for stage in result.stages)
    assert any(
        stage.name == "recent_data_acquisition_plan" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(stage.name == "provider_smoke_readiness" and stage.status == "WATCH" for stage in result.stages)
    assert any(stage.name == "tdx_day_discovery" for stage in result.stages)
    assert any(
        stage.name == "candidate_experiment_queue" and stage.status == "PASS"
        for stage in result.stages
    )
    assert any(
        stage.name == "offline_data_package" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(
        stage.name == "real_data_handoff_checklist" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(
        stage.name == "candidate_experiment_readiness" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(
        stage.name == "ohlcv_experiment_package" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(
        stage.name == "evidence_intake_kit" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(
        stage.name == "evidence_work_order" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(
        stage.name == "market_index_discovery" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(
        stage.name == "market_context_operator_packet" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(
        stage.name == "real_data_batch_onboarding" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(stage.name == "first_million_strategy_brief" for stage in result.stages)
    assert any(
        stage.name == "strategy_discovery_plan" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(
        stage.name == "first_million_evidence_ranking_dashboard" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(
        stage.name == "candidate_experiment_launch" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(
        stage.name == "candidate_experiment_run_packet" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(
        stage.name == "candidate_experiment_execution" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(
        stage.name == "candidate_experiment_completion" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(
        stage.name == "promotion_metadata_check" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(
        stage.name == "capital_goal_status" and stage.status == "BLOCK"
        for stage in result.stages
    )
    capital_stage = next(stage for stage in result.stages if stage.name == "capital_goal_status")
    assert capital_stage.message != "Goal status after data and candidate experiment gates."
    assert capital_stage.message
    assert any(
        stage.name == "compounding_path_review" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(
        stage.name == "first_million_readiness" and stage.status == "BLOCK"
        for stage in result.stages
    )
    assert any(stage.name == "weekly_pipeline" and stage.status == "SKIPPED" for stage in result.stages)
    goal_payload = json.loads((output / "goal" / "capital_goal_status.json").read_text(encoding="utf-8"))
    goal_evidence = {item["name"]: item["status"] for item in goal_payload["evidence"]}
    assert goal_evidence["csv_intake_preview"] == "PASS"
    assert goal_evidence["candidate_experiment_launch"] == "BLOCK"
    assert goal_evidence["candidate_experiment_execution"] == "BLOCK"
    assert goal_evidence["candidate_experiment_completion"] == "BLOCK"
    readiness = json.loads((output / "first_million_readiness.json").read_text(encoding="utf-8"))
    promotion_metadata = json.loads(
        (output / "promotion_metadata_check.json").read_text(encoding="utf-8")
    )
    experiment_matrix = list(
        csv.DictReader((output / "candidate_experiment_readiness_matrix.csv").open(encoding="utf-8"))
    )
    handoff_rows = list(csv.DictReader((output / "operator_handoff.csv").open(encoding="utf-8-sig")))
    source_packet = json.loads((output / "source_qa_operator_packet.json").read_text(encoding="utf-8"))
    source_closeout = json.loads((output / "source_qa_closeout.json").read_text(encoding="utf-8"))
    run_packet = json.loads((output / "candidate_experiment_run_packet.json").read_text(encoding="utf-8"))
    handoff_status = json.loads((output / "operator_handoff_status.json").read_text(encoding="utf-8"))
    resolution = json.loads(
        (output / "first_million_resolution_plan.json").read_text(encoding="utf-8")
    )
    daily_brief = json.loads((output / "first_million_daily_brief.json").read_text(encoding="utf-8"))
    evidence_kit = json.loads(
        (output / "evidence_intake_kit" / "first_million_evidence_intake_kit.json").read_text(
            encoding="utf-8"
        )
    )
    evidence_work_order = json.loads(
        (output / "first_million_evidence_work_order.json").read_text(encoding="utf-8")
    )
    discovery_plan = json.loads((output / "strategy_discovery_plan.json").read_text(encoding="utf-8"))
    evidence_ranking_dashboard = json.loads(
        (output / "first_million_evidence_ranking_dashboard.json").read_text(encoding="utf-8")
    )
    pipeline_payload = json.loads((output / "first_million_pipeline.json").read_text(encoding="utf-8"))
    raw_discovery = json.loads((output / "raw_bars_discovery.json").read_text(encoding="utf-8"))
    ohlcv_package = json.loads((output / "ohlcv_experiment_package.json").read_text(encoding="utf-8"))
    market_index_discovery = json.loads(
        (output / "market_index_discovery.json").read_text(encoding="utf-8")
    )
    market_packet = json.loads((output / "market_context_operator_packet.json").read_text(encoding="utf-8"))
    onboarding = json.loads((output / "real_data_batch_onboarding.json").read_text(encoding="utf-8"))
    data_intake_status = json.loads((output / "data_intake_status.json").read_text(encoding="utf-8"))
    resolution_rows = list(
        csv.DictReader(
            (output / "first_million_resolution_plan.csv").open(encoding="utf-8-sig")
        )
    )
    handoff_task_types = {row["task_type"] for row in handoff_rows}
    readiness_gates = {gate["name"]: gate for gate in readiness["gates"]}
    assert readiness["decision"] == "BLOCK"
    assert promotion_metadata["status"] == "BLOCK"
    assert promotion_metadata["blockers"]
    assert readiness_gates["research_cache_admissibility"]["status"] == "BLOCK"
    assert readiness_gates["current_data_cache"]["status"] == "BLOCK"
    assert readiness_gates["promotion_metadata_check"]["status"] == "BLOCK"
    assert any(gate["name"] == "recent_data_acquisition_plan" for gate in readiness["gates"])
    assert any(gate["name"] == "csv_intake_preview" for gate in readiness["gates"])
    assert any(gate["name"] == "capital_goal_status" for gate in readiness["gates"])
    assert any(gate["name"] == "compounding_path_review" for gate in readiness["gates"])
    assert result.next_actions[0].startswith("Fill ")
    assert "missing source QA worksheet rows" in result.next_actions[0]
    assert "operator_handoff.csv" in result.next_actions[0]
    assert "source_qa_worksheet_todo.csv" in result.next_actions[0]
    assert "data_vendor_or_broker" in result.next_actions[0]
    assert "run_data_source_qa_worksheet_preflight.py" in result.next_actions[1]
    assert "source QA evidence attachments" in result.next_actions[2]
    assert "source_qa_attachment_todo.csv" in result.next_actions[2]
    assert "source_qa_evidence_attachment_plan.csv" in result.next_actions[2]
    assert "source_identity" in result.next_actions[2]
    assert "write_source_qa_evidence_manifest.py" in result.next_actions[3]
    assert "operator_handoff.csv" in result.next_actions[4]
    assert "data_export_todo.csv" in result.next_actions[4]
    assert experiment_matrix[0]["candidate"] == "price_volume_defensive"
    assert experiment_matrix[0]["status"] == "BLOCKED"
    assert experiment_matrix[0]["evidence_scope"] == "OHLCV_ONLY"
    assert "source_qa_preflight=BLOCK" in experiment_matrix[0]["first_blocker"]
    assert {"source_qa_worksheet", "source_qa_attachment", "data_export"}.issubset(
        handoff_task_types
    )
    assert source_packet["decision"] == "BLOCK"
    assert source_packet["missing_worksheet_count"] == 13
    assert source_packet["missing_attachment_count"] == 5
    assert source_closeout["decision"] == "BLOCK"
    assert source_closeout["allowed_next_stage"] == "COLLECT_EVIDENCE"
    assert source_closeout["capability_flags"]["can_enter_paper"] is False
    assert source_closeout["capability_flags"]["can_generate_broker_orders"] is False
    assert run_packet["decision"] == "BLOCK"
    assert run_packet["command_bundle"] == []
    assert run_packet["capability_flags"]["can_generate_broker_orders"] is False
    assert data_intake_status["decision"] == "BLOCK"
    assert data_intake_status["summary"]["worksheet_fill_ready"] is False
    assert data_intake_status["summary"]["source_evidence_missing"] == 5
    assert any(item["area"] == "raw_bars_csv" for item in data_intake_status["items"])
    assert raw_discovery["status"] == "BLOCK"
    assert raw_discovery["best_candidate"] == ""
    assert evidence_kit["decision"] == "BLOCK"
    assert any(item["item_type"] == "source_qa_attachment" for item in evidence_kit["files"])
    assert any(item["item_type"] == "data_export_csv" for item in evidence_kit["files"])
    assert any(item["item_type"] == "market_index_csv" for item in evidence_kit["files"])
    assert evidence_work_order["decision"] == "BLOCK"
    assert evidence_work_order["next_batch_id"] == "source_qa_worksheet"
    assert evidence_work_order["batches"][0]["batch_id"] == "source_qa_worksheet"
    assert market_index_discovery["status"] == "BLOCK"
    assert market_index_discovery["best_candidate"] == ""
    assert any(
        "No candidate index CSV files" in item
        for item in market_index_discovery["candidates"][0]["findings"]
    )
    assert any("write_data_source_qa_answers.py" in item for item in source_packet["command_sequence"])
    assert any(row["id"] == "data_vendor_or_broker" for row in handoff_rows)
    bars_handoff = next(row for row in handoff_rows if row["file_name"] == "bars.csv")
    assert bars_handoff["current_state"] == "template_sample_rows"
    assert bars_handoff["row_count"] == "4"
    assert bars_handoff["symbol_count"] == "2"
    assert bars_handoff["template_rows_detected"] == "yes"
    assert bars_handoff["preview_status"] == "PASS"
    assert "symbol" in bars_handoff["mapped_columns"]
    assert bars_handoff["missing_columns"] == ""
    assert handoff_status["status"] == "BLOCK"
    assert handoff_status["open_task_count"] == len(handoff_rows)
    assert handoff_status["p0_open_task_count"] == len(handoff_rows)
    assert handoff_status["source_qa_attachment_open_task_count"] == 5
    assert resolution["decision"] == "BLOCK"
    assert resolution["pipeline_decision"] == "BLOCK"
    assert resolution["task_counts"]["P0"] >= len(handoff_rows)
    assert daily_brief["decision"] == "BLOCK"
    assert any(gate["name"] == "source_qa_closeout" for gate in daily_brief["gate_summary"])
    assert any(gate["name"] == "data_intake_status" for gate in daily_brief["gate_summary"])
    assert any(gate["name"] == "evidence_intake_kit" for gate in daily_brief["gate_summary"])
    assert any(gate["name"] == "evidence_work_order" for gate in daily_brief["gate_summary"])
    assert any(gate["name"] == "strategy_discovery_plan" for gate in daily_brief["gate_summary"])
    assert any(
        gate["name"] == "first_million_evidence_ranking_dashboard"
        for gate in daily_brief["gate_summary"]
    )
    assert daily_brief["today_focus"]["task_type"] == "source_qa_worksheet"
    assert "source_qa_worksheet" in daily_brief["top_tasks"][0]["category"]
    assert discovery_plan["decision"] == "PREPARE_DATA"
    assert discovery_plan["status"] == "BLOCK"
    assert discovery_plan["top_candidate"] == "price_volume_defensive"
    assert discovery_plan["top_candidate_basis"] == "pre_registered_priority_without_ranking"
    assert discovery_plan["can_rank_candidates"] is False
    assert discovery_plan["ranking_gate"]["status"] == "BLOCK"
    assert discovery_plan["ranking_gate"]["can_rank_candidates"] is False
    assert not any(
        "strategy_discovery_plan.json is missing" in item
        for item in discovery_plan["ranking_gate"]["blocked_by"]
    )
    assert daily_brief["ranking_status"]["status"] == "BLOCK"
    assert daily_brief["ranking_status"]["can_rank_candidates"] is False
    assert daily_brief["ranking_status"]["top_candidate_basis"] == "pre_registered_priority_without_ranking"
    assert daily_brief["ranking_status"]["first_blocker"].startswith("first_million_pipeline=BLOCK")
    assert any(
        "candidate_selection.json is missing" in item
        for item in daily_brief["ranking_status"]["blocked_by"]
    )
    assert any("strategy_ranking" in item for item in daily_brief["missing_evidence"])
    assert evidence_ranking_dashboard["decision"] == "BLOCK"
    assert evidence_ranking_dashboard["can_rank_candidates"] is False
    assert evidence_ranking_dashboard["top_candidate_basis"] == "pre_registered_priority_without_ranking"
    assert evidence_ranking_dashboard["next_area"] == "source_qa_worksheet"
    assert any(
        item["area"] == "strategy_ranking_gate"
        and item["current_state"].startswith("can_rank=false")
        for item in evidence_ranking_dashboard["items"]
    )
    assert discovery_plan["runnable_count"] == 0
    discovery_stage = next(stage for stage in result.stages if stage.name == "strategy_discovery_plan")
    pipeline_discovery_stage = next(
        stage for stage in pipeline_payload["stages"] if stage["name"] == "strategy_discovery_plan"
    )
    assert discovery_stage.artifact == str(output / "strategy_discovery_plan.json")
    assert "Strategy discovery=PREPARE_DATA" in discovery_stage.message
    assert pipeline_discovery_stage["status"] == "BLOCK"
    assert "Strategy discovery=PREPARE_DATA" in pipeline_discovery_stage["message"]
    assert ohlcv_package["decision"] == "BLOCK"
    assert ohlcv_package["candidate"] == "price_volume_defensive"
    assert ohlcv_package["bars"]["state"] == "template_sample_rows"
    assert any("source_qa_answers" in item for item in ohlcv_package["blockers"])
    assert market_packet["decision"] == "BLOCK"
    assert market_packet["readiness_source"] == "missing"
    assert any(item["item_id"] == "market_regime" for item in market_packet["items"])
    assert any("run_market_index_discovery.py" in item for item in market_packet["command_sequence"])
    assert onboarding["decision"] == "BLOCK"
    assert any("raw_bars_csv" in item for item in onboarding["blockers"])
    assert resolution_rows[0]["category"] == "source_qa_worksheet"
    assert resolution_rows[0]["source_stage"] == "operator_handoff"
    assert any(row["category"] == "source_qa_attachment" for row in resolution_rows)
    assert any(row["priority"] == "P2" for row in resolution_rows)


def test_first_million_pipeline_cache_override_reaches_all_guarded_subflows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million"
    config_cache = tmp_path / "config_default.db"
    override_cache = tmp_path / "override_recent.db"
    config = tmp_path / "research_recent.yaml"
    write_research_csv_templates(data_dir)
    _write_config(config, config_cache)
    _seed_minimal_cache(override_cache)
    weekly_call: dict[str, str] = {}

    def fake_run_weekly_pipeline(cfg, *, config_path, output_dir, **_kwargs):
        weekly_call["cache_path"] = str(cfg.data.cache_path)
        weekly_call["config_path"] = str(config_path)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        return type(
            "WeeklyResult",
            (),
            {"output_dir": str(output_dir), "weekly_decision": "research_only"},
        )()

    monkeypatch.setattr(first_million_module, "run_weekly_pipeline", fake_run_weekly_pipeline)

    result = run_first_million_pipeline(
        config_path=config,
        cache_path=override_cache,
        data_dir=data_dir,
        output_dir=output,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        registry_path=None,
    )

    readiness = json.loads((output / "first_million_readiness.json").read_text(encoding="utf-8"))
    pipeline = json.loads((output / "first_million_pipeline.json").read_text(encoding="utf-8"))
    export_request = json.loads(
        (data_dir / "data_export_request.json").read_text(encoding="utf-8")
    )
    offline_package = json.loads(
        (output / "offline_data_package.json").read_text(encoding="utf-8")
    )
    offline_intake = json.loads(
        (output / "offline_intake" / "offline_data_intake.json").read_text(encoding="utf-8")
    )
    promotion_metadata = json.loads(
        (output / "promotion_metadata_check.json").read_text(encoding="utf-8")
    )
    experiment_launch = json.loads(
        (output / "candidate_experiment_launch.json").read_text(encoding="utf-8")
    )
    experiment_run_packet = json.loads(
        (output / "candidate_experiment_run_packet.json").read_text(encoding="utf-8")
    )
    effective_config = output / "effective_config.yaml"
    current_cache = next(gate for gate in readiness["gates"] if gate["name"] == "current_data_cache")
    metadata_stage = next(stage for stage in pipeline["stages"] if stage["name"] == "promotion_metadata_check")
    stages = {stage["name"]: stage["status"] for stage in pipeline["stages"]}

    assert result.decision == "BLOCK"
    assert result.config_path == str(effective_config)
    assert effective_config.exists()
    assert first_million_module.load_config(effective_config).data.cache_path == str(override_cache)
    assert export_request["cache_path"] == str(override_cache)
    assert offline_package["config_path"] == str(effective_config)
    assert offline_intake["cache_path"] == str(override_cache)
    assert weekly_call["cache_path"] == str(override_cache)
    assert weekly_call["config_path"] == str(effective_config)
    assert experiment_launch["config_path"] == str(effective_config)
    assert experiment_run_packet["config_path"] == str(effective_config)
    assert current_cache["artifact"] == str(override_cache)
    assert "symbols=2" in current_cache["message"]
    assert "trading_days=2" in current_cache["message"]
    assert str(config_cache) not in current_cache["artifact"]
    assert promotion_metadata["cache_path"] == str(override_cache)
    assert metadata_stage["status"] == "BLOCK"
    assert stages["data_source_qa_review"] == "BLOCK"
    assert stages["candidate_experiment_launch"] == "BLOCK"
    assert stages["candidate_experiment_execution"] == "BLOCK"
    assert not (output / "weekly" / "approval_record.json").exists()


def test_first_million_pipeline_runs_research_only_weekly_when_real_cache_is_admissible(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_research_only"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)
    _seed_minimal_cache(cache)

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        registry_path=None,
    )

    pipeline = json.loads((output / "first_million_pipeline.json").read_text(encoding="utf-8"))
    readiness = json.loads((output / "first_million_readiness.json").read_text(encoding="utf-8"))
    weekly_pipeline = json.loads((output / "weekly" / "weekly_pipeline.json").read_text(encoding="utf-8"))
    llm_review = json.loads((output / "weekly" / "llm_review.json").read_text(encoding="utf-8"))
    recent_research = json.loads((output / "weekly" / "recent_candidate_research.json").read_text(encoding="utf-8"))
    strategy_brief = json.loads(
        (output / "first_million_strategy_brief.json").read_text(encoding="utf-8")
    )
    stages = {stage["name"]: stage for stage in pipeline["stages"]}
    gates = {gate["name"]: gate for gate in readiness["gates"]}
    promotion_metadata = json.loads(
        (output / "promotion_metadata_check.json").read_text(encoding="utf-8")
    )

    assert result.decision == "BLOCK"
    assert stages["offline_data_intake"]["status"] == "BLOCK"
    assert stages["promotion_metadata_check"]["status"] == "BLOCK"
    assert stages["weekly_pipeline"]["status"] in {"PASS", "WATCH"}
    assert "Research-only weekly pipeline ran on admissible real cache" in stages["weekly_pipeline"]["message"]
    assert (output / "weekly" / "weekly_pipeline.json").exists()
    assert isinstance(weekly_pipeline["weekly_decision"], str)
    assert llm_review["intended_stage"] == "research"
    assert recent_research["artifact_type"] == "recent_candidate_research"
    assert strategy_brief["compounding_goal"]["status"] == "BLOCK"
    assert strategy_brief["compounding_goal"]["capital_goal_status"] == "BLOCK"
    assert strategy_brief["compounding_goal"]["compounding_path_decision"] == "BLOCK"
    assert strategy_brief["compounding_goal"]["candidate_selection_status"] in {"PASS", "WATCH", "BLOCK"}
    assert any("compounding_goal:" in item for item in strategy_brief["missing_evidence"])
    assert gates["research_cache_admissibility"]["status"] == "PASS"
    assert gates["current_data_cache"]["status"] == "BLOCK"
    assert promotion_metadata["status"] == "BLOCK"


def test_first_million_pipeline_optionally_prepares_micro_live_readiness_materials(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_micro_prepare"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)
    _seed_minimal_cache(cache)

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        registry_path=None,
        prepare_micro_live_readiness=True,
        micro_live_candidate="price_volume_defensive",
        micro_live_capital=100_000,
    )

    pipeline = json.loads((output / "first_million_pipeline.json").read_text(encoding="utf-8"))
    weekly_pipeline = json.loads((output / "weekly" / "weekly_pipeline.json").read_text(encoding="utf-8"))
    llm_review = json.loads((output / "weekly" / "llm_review.json").read_text(encoding="utf-8"))
    readiness = json.loads((output / "weekly" / "micro_live_readiness.json").read_text(encoding="utf-8"))
    manual = pd.read_csv(output / "weekly" / "manual_trade_sheet.csv")
    stages = {stage["name"]: stage for stage in pipeline["stages"]}
    weekly_stages = {stage["name"]: stage for stage in weekly_pipeline["stages"]}

    assert result.decision == "BLOCK"
    assert llm_review["intended_stage"] == "micro_live_ready"
    assert "manual_target_plan" in stages
    assert stages["micro_live_readiness"]["status"] == "BLOCK"
    assert "broker permission" in stages["micro_live_readiness"]["message"]
    assert "manual_target_plan" in weekly_stages
    assert weekly_stages["micro_live_readiness"]["status"] == "BLOCK"
    assert (output / "weekly" / "target_portfolio.json").exists()
    assert (output / "weekly" / "risk_budget.json").exists()
    assert not (output / "weekly" / "approval_record.json").exists()
    assert readiness["decision"] == "BLOCK"
    assert any(finding["code"] == "MISSING_APPROVAL" for finding in readiness["findings"])
    assert set(manual["instruction"]) <= {"MANUAL_REFERENCE_ONLY_NO_BROKER_ORDER"}


def test_first_million_pipeline_cli_prepares_micro_live_readiness_materials(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_micro_prepare_cli"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)
    _seed_minimal_cache(cache)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_first_million_pipeline.py",
            "--config",
            str(config),
            "--data-dir",
            str(data_dir),
            "--output-dir",
            str(output),
            "--min-symbols",
            "2",
            "--min-trading-days",
            "2",
            "--as-of",
            "2024-01-03",
            "--no-registry",
            "--prepare-micro-live-readiness",
            "--micro-live-candidate",
            "price_volume_defensive",
            "--micro-live-capital",
            "100000",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    weekly = output / "weekly"
    readiness = json.loads((weekly / "micro_live_readiness.json").read_text(encoding="utf-8"))
    llm_review = json.loads((weekly / "llm_review.json").read_text(encoding="utf-8"))

    assert completed.returncode == 2
    assert (weekly / "target_portfolio.json").exists()
    assert (weekly / "manual_trade_sheet.csv").exists()
    assert (weekly / "risk_budget.json").exists()
    assert not (weekly / "approval_record.json").exists()
    assert llm_review["intended_stage"] == "micro_live_ready"
    assert readiness["decision"] == "BLOCK"
    assert any(finding["code"] == "MISSING_APPROVAL" for finding in readiness["findings"])


def test_first_million_pipeline_reads_snapshot_without_unblocking_data_gates(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_snapshot"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)
    output.mkdir()
    _write_reviewed_market_snapshot(output, label="risk_on")

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        registry_path=None,
    )

    pipeline = json.loads((output / "first_million_pipeline.json").read_text(encoding="utf-8"))
    stages = {stage["name"]: stage["status"] for stage in pipeline["stages"]}
    market_context = json.loads((output / "market_context_readiness.json").read_text(encoding="utf-8"))
    brief = json.loads((output / "first_million_strategy_brief.json").read_text(encoding="utf-8"))
    assert result.decision == "BLOCK"
    assert stages["market_index_discovery"] == "BLOCK"
    assert stages["market_context_readiness"] == "WATCH"
    assert stages["market_context_snapshot"] == "WATCH"
    assert stages["market_context_operator_packet"] == "WATCH"
    assert stages["data_gap_action_plan"] == "BLOCK"
    assert market_context["source"] == "market_context_snapshot"
    assert market_context["decision"] == "WATCH"
    assert brief["decision"] == "PREPARE_DATA"
    assert brief["market_context_source"] == "market_context_snapshot"
    assert brief["market_context_status"] == "WATCH"
    assert "market_regime.json" in "\n".join(brief["missing_evidence"])


def test_first_million_pipeline_surfaces_custom_latest_import_report(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_smoke"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    import_report = tmp_path / "smoke_akshare" / "data_import.json"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)
    _write_network_blocked_import_report(import_report)

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        latest_import_report_path=import_report,
        min_symbols=300,
        min_trading_days=240,
        as_of="2024-01-03",
        registry_path=None,
    )

    pipeline = json.loads((output / "first_million_pipeline.json").read_text(encoding="utf-8"))
    acquisition = json.loads((output / "recent_data_acquisition_plan.json").read_text(encoding="utf-8"))
    smoke = json.loads((output / "provider_smoke_readiness.json").read_text(encoding="utf-8"))
    router = json.loads((output / "data_intake_router.json").read_text(encoding="utf-8"))
    readiness = json.loads((output / "first_million_readiness.json").read_text(encoding="utf-8"))
    stages = {stage["name"]: stage for stage in pipeline["stages"]}
    routes = {route["name"]: route for route in router["routes"]}
    readiness_gates = {gate["name"]: gate for gate in readiness["gates"]}

    assert result.decision == "BLOCK"
    assert acquisition["latest_import_attempt"]["path"] == str(import_report)
    assert acquisition["latest_import_attempt"]["network_blocked"] is True
    assert acquisition["latest_import_attempt"]["actual_bar_end"] == ""
    assert smoke["status"] == "BLOCK"
    assert smoke["network_blocked"] is True
    assert smoke["recommended_route"] == "offline_csv_or_tdx"
    assert "network/proxy" in acquisition["latest_import_attempt"]["message"]
    assert str(import_report) in stages["recent_data_acquisition_plan"]["message"]
    assert "network/proxy" in stages["recent_data_acquisition_plan"]["message"]
    assert stages["provider_smoke_readiness"]["status"] == "WATCH"
    assert "network/proxy" in stages["provider_smoke_readiness"]["message"]
    assert router["latest_import_report_path"] == str(import_report)
    assert routes["provider_akshare"]["evidence"]["network_blocked"] is True
    assert routes["provider_akshare"]["evidence"]["actual_bar_end"] == ""
    assert "network/proxy" in readiness_gates["recent_data_acquisition_plan"]["message"]
    assert readiness_gates["provider_smoke_readiness"]["status"] == "WATCH"
    assert "network/proxy" in readiness_gates["provider_smoke_readiness"]["message"]


def test_first_million_pipeline_keeps_small_provider_smoke_advisory(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_smoke_pass"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    import_report = tmp_path / "smoke_akshare" / "data_import.json"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)
    _write_successful_small_import_report(import_report)

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        latest_import_report_path=import_report,
        min_symbols=300,
        min_trading_days=240,
        as_of="2024-01-03",
        registry_path=None,
    )

    pipeline = json.loads((output / "first_million_pipeline.json").read_text(encoding="utf-8"))
    smoke = json.loads((output / "provider_smoke_readiness.json").read_text(encoding="utf-8"))
    stages = {stage["name"]: stage for stage in pipeline["stages"]}

    assert result.decision == "BLOCK"
    assert smoke["status"] == "WATCH"
    assert smoke["endpoint_viability"] == "PASS"
    assert smoke["data_sufficiency_status"] == "WATCH"
    assert stages["provider_smoke_readiness"]["status"] == "WATCH"
    assert stages["data_source_qa_review"]["status"] == "BLOCK"
    assert stages["offline_data_intake"]["status"] == "BLOCK"


def test_first_million_pipeline_copies_provider_ramp_as_route_diagnostic(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_ramp"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    ramp_report = tmp_path / "provider_ramp" / "provider_acquisition_ramp.json"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)
    _write_provider_ramp_report(ramp_report, status="BLOCK")

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        provider_acquisition_ramp_report_path=ramp_report,
        min_symbols=300,
        min_trading_days=240,
        as_of="2024-01-03",
        registry_path=None,
    )

    pipeline = json.loads((output / "first_million_pipeline.json").read_text(encoding="utf-8"))
    copied_ramp = json.loads((output / "provider_acquisition_ramp.json").read_text(encoding="utf-8"))
    readiness = json.loads((output / "first_million_readiness.json").read_text(encoding="utf-8"))
    stages = {stage["name"]: stage for stage in pipeline["stages"]}
    readiness_gates = {gate["name"]: gate for gate in readiness["gates"]}

    assert result.decision == "BLOCK"
    assert copied_ramp["status"] == "BLOCK"
    assert copied_ramp["source_qa_provenance_status"] == "NOT_EVALUATED"
    assert copied_ramp["promotion_gate_effect"] == "NONE"
    assert stages["provider_acquisition_ramp"]["status"] == "WATCH"
    assert "route diagnostics only" in stages["provider_acquisition_ramp"]["message"]
    assert readiness_gates["provider_acquisition_ramp"]["status"] == "WATCH"
    assert "cannot approve source QA" in readiness_gates["provider_acquisition_ramp"]["message"]
    assert stages["data_source_qa_review"]["status"] == "BLOCK"
    assert stages["offline_data_intake"]["status"] == "BLOCK"


def test_first_million_pipeline_cli_writes_block_report(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_cli"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    tdx_root = tmp_path / "vipdoc"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)
    _write_day_file(tdx_root / "sh" / "lday" / "sh600010.day", symbol_base=10.0)
    _write_day_file(tdx_root / "sz" / "lday" / "sz000010.day", symbol_base=20.0)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_first_million_pipeline.py",
            "--config",
            str(config),
            "--data-dir",
            str(data_dir),
            "--output-dir",
            str(output),
            "--min-symbols",
            "2",
            "--min-trading-days",
            "2",
            "--tdx-search-dir",
            str(tdx_root),
            "--tdx-input-dir",
            str(tdx_root),
            "--as-of",
            "2024-01-03",
            "--no-registry",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output / "first_million_pipeline.json").read_text(encoding="utf-8"))
    router = json.loads((output / "data_intake_router.json").read_text(encoding="utf-8"))
    discovery = json.loads((output / "tdx_day_discovery.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"
    assert router["recommended_route"] == "tdx_ohlcv"
    assert router["status"] == "PASS"
    assert discovery["status"] == "PASS"
    assert discovery["best_root"] == str(tdx_root)
    assert (data_dir / "tdx_day_export.json").exists()
    assert (data_dir / "bars.csv").exists()
    assert (output / "candidate_experiment_readiness_matrix.csv").exists()
    assert any(
        stage["name"] == "tdx_day_export" and stage["status"] == "PASS"
        for stage in payload["stages"]
    )
    assert any(stage["name"] == "candidate_hypotheses" for stage in payload["stages"])
    assert any(stage["name"] == "data_gap_action_plan" for stage in payload["stages"])
    assert any(stage["name"] == "data_evidence_action_packet" for stage in payload["stages"])
    assert any(
        stage["name"] == "data_intake_router" and stage["status"] == "PASS"
        for stage in payload["stages"]
    )
    assert any(
        stage["name"] == "tdx_day_discovery" and stage["status"] == "PASS"
        for stage in payload["stages"]
    )
    assert any(stage["name"] == "offline_data_package" for stage in payload["stages"])
    assert any(stage["name"] == "real_data_handoff_checklist" for stage in payload["stages"])
    assert any(stage["name"] == "recent_data_acquisition_plan" for stage in payload["stages"])
    assert any(stage["name"] == "candidate_experiment_queue" for stage in payload["stages"])
    assert any(
        stage["name"] == "candidate_experiment_design_matrix" and stage["status"] == "PASS"
        for stage in payload["stages"]
    )
    assert any(stage["name"] == "candidate_experiment_readiness" for stage in payload["stages"])
    assert any(stage["name"] == "first_million_strategy_brief" for stage in payload["stages"])
    assert any(stage["name"] == "strategy_discovery_plan" for stage in payload["stages"])
    assert any(stage["name"] == "first_million_evidence_ranking_dashboard" for stage in payload["stages"])
    assert any(stage["name"] == "candidate_experiment_launch" for stage in payload["stages"])
    assert any(stage["name"] == "candidate_experiment_run_packet" for stage in payload["stages"])
    assert any(stage["name"] == "candidate_experiment_execution" for stage in payload["stages"])
    assert any(stage["name"] == "candidate_experiment_completion" for stage in payload["stages"])
    assert any(stage["name"] == "capital_goal_status" for stage in payload["stages"])
    assert any(stage["name"] == "compounding_path_review" for stage in payload["stages"])
    assert any(stage["name"] == "first_million_readiness" for stage in payload["stages"])
    assert any(stage["name"] == "source_qa_preflight" for stage in payload["stages"])
    assert any(stage["name"] == "data_source_qa_review" for stage in payload["stages"])
    assert any(stage["name"] == "offline_data_intake" for stage in payload["stages"])
    assert any(
        stage["name"] == "weekly_pipeline" and stage["status"] == "SKIPPED"
        for stage in payload["stages"]
    )


def test_first_million_pipeline_blocks_ambiguous_local_data_inputs(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_ambiguous"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    raw_bars = tmp_path / "raw_vendor_bars.csv"
    tdx_root = tmp_path / "vipdoc"
    _write_config(config, cache)
    _write_raw_vendor_bars(raw_bars)
    _write_day_file(tdx_root / "sh" / "lday" / "sh600010.day", symbol_base=10.0)

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        raw_bars_csv=raw_bars,
        tdx_input_dir=tdx_root,
        min_symbols=1,
        min_trading_days=2,
        as_of="2024-01-03",
        registry_path=None,
    )

    stages = {stage.name: stage for stage in result.stages}
    assert result.decision == "BLOCK"
    assert stages["data_source_selection"].status == "BLOCK"
    assert "exactly one" in stages["data_source_selection"].message
    assert "tdx_day_export" not in stages
    assert not (data_dir / "bars.csv").exists()


def test_first_million_pipeline_does_not_execute_candidate_when_ambiguous_input_blocks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_ambiguous_execute"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    raw_bars = tmp_path / "raw_vendor_bars.csv"
    tdx_root = tmp_path / "vipdoc"
    _write_config(config, cache)
    _write_ohlcv_only_export(data_dir)
    _write_optional_metadata(data_dir)
    _write_source_qa_answers(data_dir, config)
    _write_raw_vendor_bars(raw_bars)
    _write_day_file(tdx_root / "sh" / "lday" / "sh600010.day", symbol_base=10.0)

    def fail_execution(report_dir: Path, *, dry_run: bool) -> CandidateExperimentExecutionReport:
        raise AssertionError("candidate execution must not run while data_source_selection is BLOCK")

    monkeypatch.setattr(first_million_module, "run_candidate_experiment_execution", fail_execution)

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        raw_bars_csv=raw_bars,
        tdx_input_dir=tdx_root,
        source_qa_answers=data_dir / "data_source_qa_answers.json",
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        registry_path=None,
        execute_candidate_experiment=True,
    )

    pipeline = json.loads((output / "first_million_pipeline.json").read_text(encoding="utf-8"))
    readiness = json.loads((output / "candidate_experiment_readiness.json").read_text(encoding="utf-8"))
    launch = json.loads((output / "candidate_experiment_launch.json").read_text(encoding="utf-8"))
    run_packet = json.loads((output / "candidate_experiment_run_packet.json").read_text(encoding="utf-8"))
    execution = json.loads((output / "candidate_experiment_execution.json").read_text(encoding="utf-8"))
    stages = {stage["name"]: stage["status"] for stage in pipeline["stages"]}

    assert result.decision == "BLOCK"
    assert stages["data_source_selection"] == "BLOCK"
    assert stages["candidate_experiment_run_packet"] == "BLOCK"
    assert readiness["decision"] == "BLOCK"
    assert readiness["runnable_count"] == 0
    assert any("data_source_selection=BLOCK" in item for item in readiness["blockers"])
    assert launch["decision"] == "BLOCK"
    assert run_packet["decision"] == "BLOCK"
    assert run_packet["command_bundle"] == []
    assert run_packet["capability_flags"]["can_generate_broker_orders"] is False
    assert execution["decision"] == "BLOCK"


def test_first_million_pipeline_writes_tdx_source_qa_answers(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_tdx_source"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    tdx_root = tmp_path / "vipdoc"
    _write_config(config, cache)
    _write_day_file(tdx_root / "sh" / "lday" / "sh600010.day", symbol_base=10.0)
    _write_day_file(tdx_root / "sz" / "lday" / "sz000010.day", symbol_base=20.0)

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        tdx_input_dir=tdx_root,
        tdx_operator="tester",
        tdx_exported_at="2024-01-03 18:00:00",
        tdx_price_adjustment="qfq",
        tdx_price_adjustment_evidence="TDX settings panel recorded qfq before conversion",
        tdx_license_evidence="operator account permits local research and paper-trading review",
        tdx_reviewed_by="tester",
        tdx_reviewed_at="2024-01-03",
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        registry_path=None,
    )

    stages = {stage.name: stage for stage in result.stages}
    answers = json.loads((data_dir / "data_source_qa_answers.json").read_text(encoding="utf-8"))
    provenance = json.loads((output / "source_qa_answers_provenance.json").read_text(encoding="utf-8"))
    source_review = json.loads(
        (output / "source_qa" / "data_source_qa_review.json").read_text(encoding="utf-8")
    )
    assert result.decision == "BLOCK"
    assert stages["tdx_day_export"].status == "PASS"
    assert stages["source_qa_answers"].status == "PASS"
    assert stages["source_qa_answers_provenance"].status == "PASS"
    assert stages["source_qa_preflight"].status == "PASS"
    assert stages["data_source_qa_review"].status == "PASS"
    assert stages["source_qa_evidence_readiness"].status == "PASS"
    assert provenance["mode"] == "tdx_fields"
    assert provenance["input_sha256"]
    assert answers["source_metadata"]["tdx_symbol_count"] == 2
    assert "OHLCV-only" in answers["source_metadata"]["candidate_scope"]
    assert source_review["status"] == "PASS"
    assert (data_dir / "data_source_qa_evidence_worksheet.csv").exists()
    assert (data_dir / "source_qa_evidence_manifest.json").exists()
    assert (data_dir / "source_qa_evidence" / "manual_signoff.md").exists()
    goal = json.loads((output / "goal" / "capital_goal_status.json").read_text(encoding="utf-8"))
    evidence = {item["name"]: item for item in goal["evidence"]}
    assert evidence["tdx_day_traceability"]["status"] in {"PASS", "WATCH"}
    assert evidence["tdx_day_traceability"]["artifact"] != "not_applicable"


def test_first_million_pipeline_accepts_source_qa_worksheet(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_worksheet"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    _write_config(config, cache)
    _write_filled_source_qa_worksheet(data_dir, config)

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        source_qa_worksheet=data_dir / "data_source_qa_evidence_worksheet.csv",
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        registry_path=None,
    )

    stages = {stage.name: stage for stage in result.stages}
    answers = json.loads((data_dir / "data_source_qa_answers.json").read_text(encoding="utf-8"))
    provenance = json.loads((output / "source_qa_answers_provenance.json").read_text(encoding="utf-8"))
    source_review = json.loads(
        (output / "source_qa" / "data_source_qa_review.json").read_text(encoding="utf-8")
    )
    assert result.decision == "BLOCK"
    assert stages["source_qa_worksheet_preflight"].status == "PASS"
    assert stages["source_qa_answers"].status == "PASS"
    assert stages["source_qa_answers_provenance"].status == "PASS"
    assert stages["source_qa_preflight"].status == "PASS"
    assert stages["data_source_qa_review"].status == "PASS"
    assert provenance["mode"] == "worksheet"
    assert provenance["input_path"].endswith("data_source_qa_evidence_worksheet.csv")
    assert provenance["input_sha256"]
    assert provenance["checklist_sha256"]
    assert answers["source_metadata"]["data_vendor_or_broker"] == "unit-test vendor"
    assert source_review["status"] == "PASS"
    assert (output / "source_qa" / "data_source_qa_worksheet_preflight.json").exists()


def test_first_million_pipeline_strict_manifest_blocks_empty_manifest(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_strict_manifest"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    _write_config(config, cache)
    _write_source_qa_answers(data_dir, config)
    for path in (data_dir / "source_qa_evidence").glob("*"):
        if path.is_file():
            path.unlink()
    manifest = build_source_qa_evidence_manifest(
        checklist_path=data_dir / "data_source_qa.json",
        evidence_dir=data_dir / "source_qa_evidence",
    )
    write_source_qa_evidence_manifest(manifest, data_dir)

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        source_qa_answers=data_dir / "data_source_qa_answers.json",
        source_qa_evidence_manifest=data_dir / "source_qa_evidence_manifest.json",
        require_source_qa_evidence_manifest=True,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        registry_path=None,
    )

    stages = {stage.name: stage for stage in result.stages}
    package = json.loads((output / "offline_data_package.json").read_text(encoding="utf-8"))
    source_review = json.loads(
        (output / "source_qa" / "data_source_qa_review.json").read_text(encoding="utf-8")
    )
    package_items = {item["name"]: item for item in package["items"]}
    assert result.decision == "BLOCK"
    assert stages["offline_data_package"].status == "BLOCK"
    assert package["require_source_qa_evidence_manifest"] is True
    assert package_items["source_qa_review"]["status"] == "BLOCK"
    assert package_items["source_qa_evidence_manifest"]["status"] == "BLOCK"
    assert "SOURCE_QA_EVIDENCE_MANIFEST_EMPTY" in package_items["source_qa_review"]["message"]
    assert "SOURCE_QA_EVIDENCE_MANIFEST_EMPTY" in package_items["source_qa_evidence_manifest"]["message"]
    assert stages["data_source_qa_review"].status == "BLOCK"
    assert stages["offline_data_intake"].status == "BLOCK"
    assert any(
        item["code"] == "SOURCE_QA_EVIDENCE_MANIFEST_EMPTY"
        for item in source_review["findings"]
    )


def test_first_million_pipeline_blocks_mixed_generic_and_tdx_source_evidence(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_mixed_source"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    tdx_root = tmp_path / "vipdoc"
    _write_config(config, cache)
    _write_day_file(tdx_root / "sh" / "lday" / "sh600010.day", symbol_base=10.0)

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        tdx_input_dir=tdx_root,
        tdx_operator="tester",
        source_vendor="unit-test vendor",
        min_symbols=1,
        min_trading_days=2,
        as_of="2024-01-03",
        registry_path=None,
    )

    stages = {stage.name: stage for stage in result.stages}
    assert result.decision == "BLOCK"
    assert stages["source_qa_answers"].status == "BLOCK"
    assert "not both" in stages["source_qa_answers"].message
    assert not (data_dir / "data_source_qa_answers.json").exists()
    assert not (output / "source_qa_answers_provenance.json").exists()


def test_first_million_pipeline_blocks_mixed_worksheet_and_source_fields(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_mixed_worksheet"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    _write_config(config, cache)
    _write_filled_source_qa_worksheet(data_dir, config)

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        source_qa_worksheet=data_dir / "data_source_qa_evidence_worksheet.csv",
        source_vendor="unit-test vendor",
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        registry_path=None,
    )

    stages = {stage.name: stage for stage in result.stages}
    assert result.decision == "BLOCK"
    assert stages["source_qa_answers"].status == "BLOCK"
    assert "exactly one source QA evidence path" in stages["source_qa_answers"].message
    assert not (output / "source_qa_answers_provenance.json").exists()


def test_first_million_pipeline_blocks_bad_source_qa_worksheet_before_answers(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_bad_worksheet"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    _write_config(config, cache)
    _write_filled_source_qa_worksheet(data_dir, config)
    _replace_worksheet_evidence(
        data_dir / "data_source_qa_evidence_worksheet.csv",
        item_id="license_scope",
        evidence="source_qa_evidence_attachment_plan.csv",
    )

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        source_qa_worksheet=data_dir / "data_source_qa_evidence_worksheet.csv",
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        registry_path=None,
    )

    stages = {stage.name: stage for stage in result.stages}
    preflight = json.loads(
        (output / "source_qa" / "data_source_qa_worksheet_preflight.json").read_text(encoding="utf-8")
    )

    assert result.decision == "BLOCK"
    assert stages["source_qa_worksheet_preflight"].status == "BLOCK"
    assert stages["source_qa_answers"].status == "BLOCK"
    assert any(
        finding["code"] == "SOURCE_QA_WORKSHEET_GENERATED_EVIDENCE_REFERENCE"
        for finding in preflight["findings"]
    )
    assert not (data_dir / "data_source_qa_answers.json").exists()
    assert not (output / "source_qa_answers_provenance.json").exists()


def test_first_million_pipeline_cli_accepts_raw_bars_csv(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_raw_cli"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    raw_bars = tmp_path / "raw_vendor_bars.csv"
    _write_config(config, cache)
    _write_raw_vendor_bars(raw_bars)
    _write_optional_metadata(data_dir)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_first_million_pipeline.py",
            "--config",
            str(config),
            "--data-dir",
            str(data_dir),
            "--output-dir",
            str(output),
            "--raw-bars-csv",
            str(raw_bars),
            *_source_cli_args(),
            "--min-symbols",
            "2",
            "--min-trading-days",
            "2",
            "--as-of",
            "2024-01-03",
            "--no-registry",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output / "first_million_pipeline.json").read_text(encoding="utf-8"))
    stages = {stage["name"]: stage["status"] for stage in payload["stages"]}
    assert completed.returncode == 2
    assert stages["source_qa_answers"] == "PASS"
    assert stages["source_qa_answers_provenance"] == "PASS"
    assert stages["source_qa_preflight"] == "PASS"
    assert stages["vendor_bars_normalization"] == "PASS"
    assert (data_dir / "data_source_qa_answers.json").exists()
    assert (output / "source_qa_answers_provenance.json").exists()
    assert (output / "source_qa_answers_input_snapshot.json").exists()
    assert (output / "vendor_bars_normalization.json").exists()
    assert (output / "offline_intake" / "vendor_bars_normalization.json").exists()
    assert (output / "run_manifest.json").exists()


def test_first_million_pipeline_cli_execute_flag_disables_dry_run_mode_on_blocked_launch(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_execute_cli"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_first_million_pipeline.py",
            "--config",
            str(config),
            "--data-dir",
            str(data_dir),
            "--output-dir",
            str(output),
            "--min-symbols",
            "2",
            "--min-trading-days",
            "2",
            "--as-of",
            "2024-01-03",
            "--no-registry",
            "--execute-candidate-experiment",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    run_packet = json.loads((output / "candidate_experiment_run_packet.json").read_text(encoding="utf-8"))
    execution = json.loads((output / "candidate_experiment_execution.json").read_text(encoding="utf-8"))
    pipeline = json.loads((output / "first_million_pipeline.json").read_text(encoding="utf-8"))
    stages = {stage["name"]: stage["status"] for stage in pipeline["stages"]}
    assert completed.returncode == 2
    assert stages["candidate_experiment_launch"] == "BLOCK"
    assert stages["candidate_experiment_run_packet"] == "BLOCK"
    assert stages["candidate_experiment_execution"] == "BLOCK"
    assert run_packet["decision"] == "BLOCK"
    assert run_packet["command_bundle"] == []
    assert execution["dry_run"] is False
    assert execution["steps"] == []
    assert "requires PASS" in execution["blockers"][0]


def test_first_million_pipeline_readiness_uses_handoff_payload_for_candidate_paths(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    _write_config(config, cache)
    from quantify.utils.config import load_config

    cfg = load_config(config)
    queue = build_candidate_experiment_queue(
        cfg,
        as_of="2026-06-08",
        catalog=build_candidate_hypothesis_catalog(cfg, as_of="2026-06-08"),
    )
    stages = [
        FirstMillionPipelineStage("candidate_experiment_queue", "PASS", "queue.json", "queue"),
        FirstMillionPipelineStage("offline_data_package", "WATCH", "package.json", "package watch"),
        FirstMillionPipelineStage("source_qa_preflight", "PASS", "preflight.json", "preflight pass"),
        FirstMillionPipelineStage("data_source_qa_review", "PASS", "qa.json", "qa pass"),
        FirstMillionPipelineStage("offline_data_intake", "WATCH", "intake.json", "intake watch"),
    ]
    readiness = build_candidate_experiment_readiness(
        queue,
        stage_statuses={stage.name: stage.status for stage in stages},
        stage_messages={stage.name: stage.message for stage in stages},
        handoff_payload={
            "evidence_paths": [
                {"name": "ohlcv_minimum_path", "status": "PASS", "blocked_by": []},
                {
                    "name": "pit_fundamental_candidate_path",
                    "status": "BLOCK",
                    "blocked_by": ["fundamentals.csv is missing."],
                },
            ]
        },
        as_of="2026-06-08",
    )

    assert readiness.decision == "WATCH"
    assert readiness.runnable_count == 13
    assert readiness.items[0].candidate == "price_volume_defensive"
    assert readiness.items[0].status == "READY"
    assert readiness.items[1].candidate == "low_turnover_price_volume"
    assert readiness.items[1].status == "READY"
    assert readiness.items[2].candidate == "low_turnover_low_concentration_price_volume"
    assert readiness.items[2].status == "READY"
    assert readiness.items[3].candidate == "trend_filtered_price_volume"
    assert readiness.items[3].status == "READY"
    assert readiness.items[4].candidate == "trend_filtered_quarterly_price_volume"
    assert readiness.items[4].status == "READY"
    assert readiness.items[5].candidate == "trend_filtered_quarterly_low_concentration_price_volume"
    assert readiness.items[5].status == "READY"
    assert readiness.items[6].candidate == "defensive_scaled_quarterly_price_volume"
    assert readiness.items[6].status == "READY"
    assert readiness.items[7].candidate == "stable_universe_slow_signal_price_volume"
    assert readiness.items[7].status == "READY"
    assert readiness.items[8].candidate == "long_momentum_liquidity_monthly_price_volume"
    assert readiness.items[8].status == "READY"
    assert readiness.items[9].candidate == "liquidity_neutral_momentum_guard_price_volume"
    assert readiness.items[9].status == "READY"
    assert readiness.items[10].candidate == "defensive_cash_guard_price_volume"
    assert readiness.items[10].status == "READY"
    assert readiness.items[11].candidate == "risk_off_cash_stop_price_volume"
    assert readiness.items[11].status == "READY"
    assert readiness.items[12].candidate == "regime_pause_price_volume"
    assert readiness.items[12].status == "READY"
    assert all(item.status == "BLOCKED" for item in readiness.items[13:])


def test_first_million_pipeline_rehearses_ohlcv_only_launch_while_pit_stays_blocked(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    _write_config(config, cache)
    _write_ohlcv_only_export(data_dir)
    _write_source_qa_answers(data_dir, config)
    output.mkdir()
    _write_reviewed_market_snapshot(output, label="neutral")

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        source_qa_answers=data_dir / "data_source_qa_answers.json",
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        registry_path=None,
    )

    handoff = json.loads((output / "real_data_handoff_checklist.json").read_text(encoding="utf-8"))
    paths = {item["name"]: item for item in handoff["evidence_paths"]}
    readiness = json.loads((output / "candidate_experiment_readiness.json").read_text(encoding="utf-8"))
    items = {item["candidate"]: item for item in readiness["items"]}
    launch = json.loads((output / "candidate_experiment_launch.json").read_text(encoding="utf-8"))
    run_packet = json.loads((output / "candidate_experiment_run_packet.json").read_text(encoding="utf-8"))
    execution = json.loads((output / "candidate_experiment_execution.json").read_text(encoding="utf-8"))
    pipeline = json.loads((output / "first_million_pipeline.json").read_text(encoding="utf-8"))
    router = json.loads((output / "data_intake_router.json").read_text(encoding="utf-8"))
    stages = {stage["name"]: stage["status"] for stage in pipeline["stages"]}

    assert result.decision == "BLOCK"
    assert stages["offline_data_package"] == "WATCH"
    assert stages["data_intake_router"] == "WATCH"
    assert stages["offline_data_intake"] == "WATCH"
    assert stages["candidate_experiment_run_packet"] == "PASS"
    assert stages["candidate_experiment_execution"] == "WATCH"
    assert stages["weekly_pipeline"] == "WATCH"
    assert paths["ohlcv_minimum_path"]["status"] == "PASS"
    assert paths["pit_fundamental_candidate_path"]["status"] == "BLOCK"
    assert router["recommended_route"] == "broker_vendor_csv"
    assert readiness["decision"] == "WATCH"
    assert readiness["runnable_count"] == 13
    assert items["price_volume_defensive"]["status"] == "READY"
    assert items["price_volume_defensive"]["evidence_scope"] == "OHLCV_ONLY"
    assert items["price_volume_defensive"]["evidence_path_status"] == "PASS"
    assert items["low_turnover_price_volume"]["status"] == "READY"
    assert items["low_turnover_price_volume"]["evidence_scope"] == "OHLCV_ONLY"
    assert items["low_turnover_price_volume"]["evidence_path_status"] == "PASS"
    assert items["low_turnover_low_concentration_price_volume"]["status"] == "READY"
    assert items["low_turnover_low_concentration_price_volume"]["evidence_scope"] == "OHLCV_ONLY"
    assert items["low_turnover_low_concentration_price_volume"]["evidence_path_status"] == "PASS"
    assert items["trend_filtered_price_volume"]["status"] == "READY"
    assert items["trend_filtered_price_volume"]["evidence_scope"] == "OHLCV_ONLY"
    assert items["trend_filtered_price_volume"]["evidence_path_status"] == "PASS"
    assert items["trend_filtered_quarterly_price_volume"]["status"] == "READY"
    assert items["trend_filtered_quarterly_price_volume"]["evidence_scope"] == "OHLCV_ONLY"
    assert items["trend_filtered_quarterly_price_volume"]["evidence_path_status"] == "PASS"
    assert items["trend_filtered_quarterly_low_concentration_price_volume"]["status"] == "READY"
    assert (
        items["trend_filtered_quarterly_low_concentration_price_volume"]["evidence_scope"]
        == "OHLCV_ONLY"
    )
    assert (
        items["trend_filtered_quarterly_low_concentration_price_volume"]["evidence_path_status"]
        == "PASS"
    )
    assert items["defensive_scaled_quarterly_price_volume"]["status"] == "READY"
    assert items["defensive_scaled_quarterly_price_volume"]["evidence_scope"] == "OHLCV_ONLY"
    assert items["defensive_scaled_quarterly_price_volume"]["evidence_path_status"] == "PASS"
    assert items["stable_universe_slow_signal_price_volume"]["status"] == "READY"
    assert items["stable_universe_slow_signal_price_volume"]["evidence_scope"] == "OHLCV_ONLY"
    assert items["stable_universe_slow_signal_price_volume"]["evidence_path_status"] == "PASS"
    assert items["long_momentum_liquidity_monthly_price_volume"]["status"] == "READY"
    assert items["long_momentum_liquidity_monthly_price_volume"]["evidence_scope"] == "OHLCV_ONLY"
    assert items["long_momentum_liquidity_monthly_price_volume"]["evidence_path_status"] == "PASS"
    assert items["liquidity_neutral_momentum_guard_price_volume"]["status"] == "READY"
    assert items["liquidity_neutral_momentum_guard_price_volume"]["evidence_scope"] == "OHLCV_ONLY"
    assert items["liquidity_neutral_momentum_guard_price_volume"]["evidence_path_status"] == "PASS"
    assert items["defensive_cash_guard_price_volume"]["status"] == "READY"
    assert items["defensive_cash_guard_price_volume"]["evidence_scope"] == "OHLCV_ONLY"
    assert items["defensive_cash_guard_price_volume"]["evidence_path_status"] == "PASS"
    assert items["risk_off_cash_stop_price_volume"]["status"] == "READY"
    assert items["risk_off_cash_stop_price_volume"]["evidence_scope"] == "OHLCV_ONLY"
    assert items["risk_off_cash_stop_price_volume"]["evidence_path_status"] == "PASS"
    assert items["regime_pause_price_volume"]["status"] == "READY"
    assert items["regime_pause_price_volume"]["evidence_scope"] == "OHLCV_ONLY"
    assert items["regime_pause_price_volume"]["evidence_path_status"] == "PASS"
    assert items["price_volume_defensive"]["source_provenance"].startswith(
        "source=unit-test vendor / unit-test terminal"
    )
    assert "daily bars" in "\n".join(items["price_volume_defensive"]["required_evidence_notes"])
    assert items["price_volume_defensive"]["warnings"]
    assert items["core_multifactor"]["status"] == "BLOCKED"
    assert items["core_multifactor"]["evidence_scope"] == "PIT_FUNDAMENTAL_REQUIRED"
    assert items["core_multifactor"]["evidence_path_status"] == "BLOCK"
    assert "PIT" in "\n".join(items["core_multifactor"]["required_evidence_notes"])
    assert "fundamentals.csv" in "\n".join(items["core_multifactor"]["blocked_by"])
    assert launch["decision"] == "PASS"
    assert launch["selected_candidate"] == "price_volume_defensive"
    assert "run_candidate_experiment_evidence.py" in launch["command_sequence"][0]
    assert "run_candidate_walk_forward.py" in launch["command_sequence"][1]
    assert "--candidate price_volume_defensive" in launch["command_sequence"][1]
    assert any(
        "run_candidate_selection.py" in command and "--candidate price_volume_defensive" in command
        for command in launch["command_sequence"]
    )
    assert not any("core_multifactor" in command for command in launch["command_sequence"])
    assert run_packet["decision"] == "PASS"
    assert run_packet["selected_candidate"] == "price_volume_defensive"
    assert run_packet["command_bundle"]
    assert run_packet["capability_flags"]["can_generate_broker_orders"] is False
    run_packet_commands = "\n".join(item["command"] for item in run_packet["command_bundle"])
    assert "run_candidate_experiment_execution.py" in run_packet_commands
    assert "broker" not in run_packet_commands.lower()
    assert execution["decision"] == "DRY_RUN"
    assert execution["dry_run"] is True
    assert len(execution["steps"]) == len(launch["command_sequence"])
    assert all(step["status"] == "SKIPPED" for step in execution["steps"])


def test_first_million_pipeline_execute_candidate_experiment_is_explicit_opt_in(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    _write_config(config, cache)
    _write_ohlcv_only_export(data_dir)
    _write_source_qa_answers(data_dir, config)
    output.mkdir()
    _write_reviewed_market_snapshot(output, label="neutral")
    calls: list[dict[str, object]] = []

    def fake_execution(report_dir: Path, *, dry_run: bool) -> CandidateExperimentExecutionReport:
        calls.append({"report_dir": report_dir, "dry_run": dry_run})
        return CandidateExperimentExecutionReport(
            decision="PASS",
            launch_path=str(Path(report_dir) / "candidate_experiment_launch.json"),
            report_dir=str(report_dir),
            experiment_dir=str(Path(report_dir) / "candidate_experiments" / "fake"),
            selected_candidate="price_volume_defensive",
            run_id="fake",
            dry_run=dry_run,
            steps=[
                CandidateExperimentExecutionStep(
                    index=1,
                    command="python examples/run_candidate_experiment_evidence.py",
                    status="PASS",
                    returncode=0,
                    stdout_log="stdout.log",
                    stderr_log="stderr.log",
                    message="mocked research-only command completed.",
                )
            ],
            blockers=[],
            next_actions=["Run candidate_experiment_completion to verify required artifacts."],
            prohibited_actions=[
                "Do not connect candidate experiment execution to real broker order submission.",
                "Do not treat execution PASS as profitability, paper promotion, or micro-live readiness.",
            ],
        )

    monkeypatch.setattr(first_million_module, "run_candidate_experiment_execution", fake_execution)

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        source_qa_answers=data_dir / "data_source_qa_answers.json",
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        registry_path=None,
        execute_candidate_experiment=True,
    )

    pipeline = json.loads((output / "first_million_pipeline.json").read_text(encoding="utf-8"))
    stages = {stage["name"]: stage["status"] for stage in pipeline["stages"]}
    run_packet = json.loads((output / "candidate_experiment_run_packet.json").read_text(encoding="utf-8"))
    execution = json.loads((output / "candidate_experiment_execution.json").read_text(encoding="utf-8"))

    assert result.decision == "BLOCK"
    assert calls == [{"report_dir": output, "dry_run": False}]
    assert stages["candidate_experiment_launch"] == "PASS"
    assert stages["candidate_experiment_run_packet"] == "PASS"
    assert stages["candidate_experiment_execution"] == "PASS"
    assert run_packet["decision"] == "PASS"
    assert run_packet["capability_flags"]["can_execute_without_operator_opt_in"] is False
    assert any(
        item["phase"] == "explicit_execution" and item["requires_explicit_operator_opt_in"] is True
        for item in run_packet["command_bundle"]
    )
    assert execution["decision"] == "PASS"
    assert execution["dry_run"] is False
    assert "profitability" in "\n".join(execution["prohibited_actions"])
    assert "broker" in "\n".join(execution["prohibited_actions"]).lower()


def test_first_million_pipeline_accepts_raw_vendor_bars_csv(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_raw"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    raw_bars = tmp_path / "raw_vendor_bars.csv"
    _write_config(config, cache)
    _write_raw_vendor_bars(raw_bars)
    _write_optional_metadata(data_dir)

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        raw_bars_csv=raw_bars,
        **_source_kwargs(),
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        registry_path=None,
    )

    pipeline = json.loads((output / "first_million_pipeline.json").read_text(encoding="utf-8"))
    stages = {stage["name"]: stage["status"] for stage in pipeline["stages"]}
    normalization = json.loads((output / "vendor_bars_normalization.json").read_text(encoding="utf-8"))
    intake_normalization = json.loads(
        (output / "offline_intake" / "vendor_bars_normalization.json").read_text(encoding="utf-8")
    )
    import_report = json.loads((output / "offline_intake" / "data_import.json").read_text(encoding="utf-8"))
    goal = json.loads((output / "goal" / "capital_goal_status.json").read_text(encoding="utf-8"))
    evidence = {item["name"]: item for item in goal["evidence"]}

    assert result.decision == "BLOCK"
    assert stages["source_qa_answers"] == "PASS"
    assert stages["vendor_bars_normalization"] == "PASS"
    assert stages["offline_data_intake"] in {"PASS", "WATCH"}
    assert stages["promotion_metadata_check"] == "BLOCK"
    assert (data_dir / "bars.csv").exists()
    assert normalization["raw_sha256"] == intake_normalization["raw_sha256"]
    assert import_report["metadata"]["raw_vendor_bars_sha256"] == normalization["raw_sha256"]
    assert evidence["raw_vendor_traceability"]["status"] in {"PASS", "WATCH"}
    assert "vendor_bars_normalization" in {stage["name"] for stage in pipeline["stages"]}
    assert (data_dir / "data_source_qa_answers.json").exists()
    promotion_metadata = json.loads(
        (output / "promotion_metadata_check.json").read_text(encoding="utf-8")
    )
    assert any("data_source_qa_status is WATCH" in item for item in promotion_metadata["blockers"])


def test_first_million_pipeline_accepts_raw_bars_with_source_qa_worksheet(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_raw_worksheet"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    raw_bars = tmp_path / "raw_vendor_bars.csv"
    _write_config(config, cache)
    _write_raw_vendor_bars(raw_bars)
    _write_optional_metadata(data_dir)
    _write_filled_source_qa_worksheet(data_dir, config)

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        raw_bars_csv=raw_bars,
        source_qa_worksheet=data_dir / "data_source_qa_evidence_worksheet.csv",
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        registry_path=None,
    )

    pipeline = json.loads((output / "first_million_pipeline.json").read_text(encoding="utf-8"))
    stages = {stage["name"]: stage["status"] for stage in pipeline["stages"]}
    answers = json.loads((data_dir / "data_source_qa_answers.json").read_text(encoding="utf-8"))
    source_review = json.loads(
        (output / "source_qa" / "data_source_qa_review.json").read_text(encoding="utf-8")
    )
    normalization = json.loads((output / "vendor_bars_normalization.json").read_text(encoding="utf-8"))
    intake_normalization = json.loads(
        (output / "offline_intake" / "vendor_bars_normalization.json").read_text(encoding="utf-8")
    )

    assert result.decision == "BLOCK"
    assert stages["vendor_bars_normalization"] == "PASS"
    assert stages["raw_bars_discovery"] == "PASS"
    assert stages["source_qa_worksheet_preflight"] == "PASS"
    assert stages["source_qa_answers"] == "PASS"
    assert stages["source_qa_preflight"] == "PASS"
    assert stages["data_source_qa_review"] == "PASS"
    assert stages["source_qa_evidence_readiness"] == "BLOCK"
    assert stages["offline_data_intake"] in {"PASS", "WATCH"}
    assert stages["promotion_metadata_check"] == "BLOCK"
    assert answers["source_metadata"]["data_vendor_or_broker"] == "unit-test vendor"
    assert source_review["status"] == "PASS"
    assert normalization["raw_sha256"] == intake_normalization["raw_sha256"]
    assert (output / "run_manifest.json").exists()
    promotion_metadata = json.loads(
        (output / "promotion_metadata_check.json").read_text(encoding="utf-8")
    )
    assert any("data_source_qa_status is WATCH" in item for item in promotion_metadata["blockers"])


def test_first_million_pipeline_blocks_partial_source_evidence_fields(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "first_million_partial_source"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    raw_bars = tmp_path / "raw_vendor_bars.csv"
    _write_config(config, cache)
    _write_raw_vendor_bars(raw_bars)
    _write_optional_metadata(data_dir)

    result = run_first_million_pipeline(
        config_path=config,
        data_dir=data_dir,
        output_dir=output,
        raw_bars_csv=raw_bars,
        source_vendor="unit-test vendor",
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        registry_path=None,
    )

    pipeline = json.loads((output / "first_million_pipeline.json").read_text(encoding="utf-8"))
    stages = {stage["name"]: stage for stage in pipeline["stages"]}
    assert result.decision == "BLOCK"
    assert stages["source_qa_answers"]["status"] == "BLOCK"
    assert stages["source_qa_preflight"]["status"] == "BLOCK"
    assert "source_terminal" in stages["source_qa_answers"]["message"]
    assert "data_source_qa_answers.json" in stages["source_qa_preflight"]["message"]
    assert not (data_dir / "data_source_qa_answers.json").exists()


def _write_config(path: Path, cache: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "research:",
                '  start: "2024-01-02"',
                '  end: "2024-01-03"',
                '  in_sample_end: "2024-01-02"',
                '  out_sample_start: "2024-01-03"',
                "  initial_cash: 1000000.0",
                "  rebalance: monthly",
                "  allow_demo_data: false",
                "data:",
                "  source: csv",
                f"  cache_path: '{cache}'",
                "  adjust: qfq",
                "universe:",
                "  index_code: '000906'",
                "  mode: all_a",
                "  include_st: false",
                "  min_history_days: 1",
                "strategy:",
                "  n_holdings: 2",
                "  max_weight: 0.10",
                "risk:",
                "  max_drawdown_stop: 0.2",
                "broker:",
                "  commission_rate: 0.0",
                "  min_commission: 0.0",
                "  stamp_tax: 0.0",
                "  slippage_bps: 0.0",
                "  price_limit_pct: 0.10",
                "  lot_size: 100",
                "output:",
                f"  results_dir: '{path.parent / 'results'}'",
            ]
        ),
        encoding="utf-8",
    )


def _seed_minimal_cache(cache: Path) -> None:
    storage = BarStorage(cache)
    storage.save_calendar(["2024-01-02", "2024-01-03"])
    storage.save_stock_info(
        pd.DataFrame(
            {
                "symbol": ["600010", "000010"],
                "name": ["RealishSSE", "RealishSZSE"],
                "exchange": ["SSE", "SZSE"],
                "list_date": ["2001-01-01", "2002-01-01"],
                "delist_date": ["", ""],
                "industry": ["industry_a", "industry_b"],
                "is_st": [0, 0],
            }
        )
    )
    storage.save_bars(
        pd.DataFrame(
            {
                "symbol": ["600010", "600010", "000010", "000010"],
                "date": ["2024-01-02", "2024-01-03", "2024-01-02", "2024-01-03"],
                "open": [11.0, 11.1, 21.0, 21.1],
                "high": [11.5, 11.6, 21.5, 21.6],
                "low": [10.8, 11.0, 20.8, 21.0],
                "close": [11.2, 11.3, 21.2, 21.3],
                "volume": [1_500_000, 1_600_000, 2_500_000, 2_600_000],
                "amount": [16_800_000, 18_080_000, 53_000_000, 55_380_000],
            }
        )
    )


def _write_reviewed_market_snapshot(root: Path, *, label: str = "neutral") -> None:
    (root / "market_context_snapshot.json").write_text(
        json.dumps(
            {
                "artifact_type": "market_context_snapshot",
                "status": "PASS",
                "label": label,
                "as_of": "2024-01-03",
                "source": "unit-test reviewed index export",
                "reviewed_by": "tester",
                "reviewed_at": "2024-01-03",
                "index_metrics": [
                    {
                        "name": "CSI300",
                        "return_20d": 0.01,
                        "return_60d": 0.02,
                        "return_120d": 0.03,
                        "max_drawdown": 0.05,
                        "annualized_volatility": 0.18,
                        "breadth_above_ma20": 0.55,
                        "breadth_above_ma60": 0.50,
                        "note": "unit-test reviewed close.",
                    }
                ],
                "can_replace_market_regime": False,
                "can_approve_strategy": False,
                "can_generate_broker_orders": False,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_network_blocked_import_report(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": "BLOCK",
                "start": "2024-01-02",
                "end": "2024-01-03",
                "requested_symbols": 2,
                "imported_symbols": 0,
                "failed_symbols": 2,
                "bar_rows": 0,
                "calendar_days": 0,
                "network_blocked": True,
                "failures": [
                    {
                        "symbol": "000001",
                        "reason": "ProxyError: Unable to connect to proxy",
                    }
                ],
                "metadata": {
                    "actual_bar_start": "",
                    "actual_bar_end": "",
                    "actual_bar_symbol_count": 0,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_successful_small_import_report(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": "PASS",
                "start": "2024-01-02",
                "end": "2024-01-03",
                "requested_symbols": 2,
                "imported_symbols": 2,
                "failed_symbols": 0,
                "bar_rows": 4,
                "calendar_days": 2,
                "failures": [],
                "metadata": {
                    "actual_bar_start": "2024-01-02",
                    "actual_bar_end": "2024-01-03",
                    "actual_bar_symbol_count": 2,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_provider_ramp_report(path: Path, *, status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": status,
                "provider": "akshare",
                "start": "2024-01-02",
                "end": "2024-01-03",
                "cache_path": str(path.parent / "provider_ramp.db"),
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
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_source_qa_answers(data_dir: Path, config: Path) -> None:
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=2,
        as_of="2024-01-03",
    )
    write_data_source_qa(checklist, data_dir)
    answers = build_data_source_qa_answers(
        checklist_path=data_dir / "data_source_qa.json",
        data_vendor_or_broker="unit-test vendor",
        terminal_or_product_name="unit-test terminal",
        export_operator="tester",
        exported_at_local_time="2024-01-03 18:00:00",
        price_adjustment="qfq",
        price_adjustment_evidence="vendor export setting says qfq",
        license_or_usage_scope="research and paper trading only",
        license_evidence="unit-test license note",
        point_in_time_evidence=(
            "OHLCV-only package; PIT fundamentals and PIT index constituents are not supplied, "
            "so fundamental-dependent candidates remain blocked."
        ),
        reviewed_by="tester",
        reviewed_at="2024-01-03",
    )
    write_data_source_qa_answers(answers, data_dir / "data_source_qa_answers.json")
    _write_required_source_qa_attachments(data_dir, checklist.to_dict())


def _write_required_source_qa_attachments(data_dir: Path, checklist: dict[str, object]) -> None:
    evidence_dir = data_dir / "source_qa_evidence"
    for item in checklist.get("checklist", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("review_stage") != "source" or item.get("severity") != "BLOCK_IF_NO":
            continue
        item_id = str(item.get("id", ""))
        path = evidence_dir / f"{item_id}_evidence.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"vendor export audit note for {item_id}: retained screenshot/document reviewed by tester.",
            encoding="utf-8",
        )
    manifest = build_source_qa_evidence_manifest(
        checklist_path=data_dir / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, data_dir)


def _write_filled_source_qa_worksheet(data_dir: Path, config: Path) -> None:
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=2,
        as_of="2024-01-03",
    )
    write_data_source_qa(checklist, data_dir)
    worksheet = build_data_source_qa_evidence_worksheet(
        checklist_path=data_dir / "data_source_qa.json",
        output_dir=data_dir,
    )
    values = {
        "data_vendor_or_broker": "unit-test vendor",
        "terminal_or_product_name": "unit-test terminal",
        "export_operator": "tester",
        "exported_at_local_time": "2024-01-03 18:00:00",
        "price_adjustment": "qfq",
        "license_or_usage_scope": "research and paper trading only",
        "reviewed_by": "tester",
        "reviewed_at": "2024-01-03",
    }
    evidence = {
        "source_identity": "vendor export receipt identifies source, terminal, operator, and timestamp",
        "license_scope": "unit-test license note allows local research and paper-trading review",
        "price_adjustment": "vendor export setting says qfq",
        "point_in_time": (
            "OHLCV-only package; PIT fundamentals and PIT index constituents are not supplied, "
            "so fundamental-dependent candidates remain blocked."
        ),
        "manual_signoff": "reviewed_by=tester; reviewed_at=2024-01-03",
    }
    rows = []
    for row in worksheet.rows:
        payload = row.to_dict()
        key = payload["field_or_question_id"]
        if payload["row_type"] == "metadata" and key in values:
            payload["answer"] = values[key]
            payload["evidence"] = f"vendor export metadata record for {key}"
        if payload["row_type"] == "source_question":
            payload["answer"] = "yes"
            payload["evidence"] = evidence.get(key, f"source evidence for {key}")
        rows.append(payload)
    with (data_dir / "data_source_qa_evidence_worksheet.csv").open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        fieldnames = [
            "row_type",
            "field_or_question_id",
            "cli_argument",
            "severity",
            "question_or_field",
            "required_evidence",
            "why_it_matters",
            "answer",
            "evidence",
            "notes",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _replace_worksheet_evidence(path: Path, *, item_id: str, evidence: str) -> None:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    for row in rows:
        if str(row.get("field_or_question_id", "")) == item_id:
            row["evidence"] = evidence
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _source_kwargs() -> dict[str, str]:
    return {
        "source_vendor": "unit-test vendor",
        "source_terminal": "unit-test terminal",
        "source_operator": "tester",
        "source_exported_at": "2024-01-03 18:00:00",
        "source_price_adjustment": "qfq",
        "source_price_adjustment_evidence": "vendor export setting says qfq",
        "source_license_evidence": "unit-test license note",
        "source_point_in_time_evidence": (
            "OHLCV-only package; PIT fundamentals and PIT index constituents are not supplied, "
            "so fundamental-dependent candidates remain blocked."
        ),
        "source_reviewed_by": "tester",
        "source_reviewed_at": "2024-01-03",
    }


def _source_cli_args() -> list[str]:
    values = _source_kwargs()
    return [
        "--source-vendor",
        values["source_vendor"],
        "--source-terminal",
        values["source_terminal"],
        "--source-operator",
        values["source_operator"],
        "--source-exported-at",
        values["source_exported_at"],
        "--source-price-adjustment",
        values["source_price_adjustment"],
        "--source-price-adjustment-evidence",
        values["source_price_adjustment_evidence"],
        "--source-license-evidence",
        values["source_license_evidence"],
        "--source-point-in-time-evidence",
        values["source_point_in_time_evidence"],
        "--source-reviewed-by",
        values["source_reviewed_by"],
        "--source-reviewed-at",
        values["source_reviewed_at"],
    ]


def _write_ohlcv_only_export(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "symbol": ["600010", "600010", "000010", "000010"],
            "date": ["2024-01-02", "2024-01-03", "2024-01-02", "2024-01-03"],
            "open": [11.0, 11.1, 21.0, 21.1],
            "high": [11.5, 11.6, 21.5, 21.6],
            "low": [10.8, 11.0, 20.8, 21.0],
            "close": [11.2, 11.3, 21.2, 21.3],
            "volume": [1_500_000, 1_600_000, 2_500_000, 2_600_000],
            "amount": [16_800_000, 18_080_000, 53_000_000, 55_380_000],
        }
    ).to_csv(data_dir / "bars.csv", index=False)
    pd.DataFrame(
        {
            "symbol": ["600010", "000010"],
            "name": ["RealishSSE", "RealishSZSE"],
            "exchange": ["SSE", "SZSE"],
            "list_date": ["2001-01-01", "2002-01-01"],
            "delist_date": ["", ""],
            "industry": ["industry_a", "industry_b"],
            "is_st": [0, 0],
        }
    ).to_csv(data_dir / "stock_info.csv", index=False)
    pd.DataFrame({"date": ["2024-01-02", "2024-01-03", "2024-01-04"], "is_open": [1, 1, 0]}).to_csv(
        data_dir / "calendar.csv",
        index=False,
    )
    pd.DataFrame(
        {
            "symbol": ["600010", "000010"],
            "date": ["2024-01-03", "2024-01-03"],
            "is_suspended": [0, 0],
        }
    ).to_csv(data_dir / "suspensions.csv", index=False)


def _write_optional_metadata(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "symbol": ["600010", "000010"],
            "name": ["RealishSSE", "RealishSZSE"],
            "exchange": ["SSE", "SZSE"],
            "list_date": ["2001-01-01", "2002-01-01"],
            "delist_date": ["", ""],
            "industry": ["industry_a", "industry_b"],
            "is_st": [0, 0],
        }
    ).to_csv(data_dir / "stock_info.csv", index=False)
    pd.DataFrame({"date": ["2024-01-02", "2024-01-03", "2024-01-04"], "is_open": [1, 1, 0]}).to_csv(
        data_dir / "calendar.csv",
        index=False,
    )
    pd.DataFrame(
        {
            "symbol": ["600010", "000010"],
            "date": ["2024-01-03", "2024-01-03"],
            "is_suspended": [0, 0],
        }
    ).to_csv(data_dir / "suspensions.csv", index=False)


def _write_day_file(path: Path, *, symbol_base: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = struct.Struct("<IIIIIfII")
    rows = [
        record.pack(
            20240102,
            int(symbol_base * 100),
            int((symbol_base + 0.5) * 100),
            int((symbol_base - 0.2) * 100),
            int((symbol_base + 0.2) * 100),
            float((symbol_base + 0.2) * 1_000_000),
            1_000_000,
            0,
        ),
        record.pack(
            20240103,
            int((symbol_base + 0.2) * 100),
            int((symbol_base + 0.8) * 100),
            int((symbol_base + 0.1) * 100),
            int((symbol_base + 0.6) * 100),
            float((symbol_base + 0.6) * 1_100_000),
            1_100_000,
            0,
        ),
    ]
    path.write_bytes(b"".join(rows))


def _write_raw_vendor_bars(path: Path) -> None:
    pd.DataFrame(
        {
            "symbol": ["600010.SH", "600010.SH", "SZ000010", "SZ000010"],
            "date": [20240102, 20240103, 20240102, 20240103],
            "open": [11.0, 11.1, 21.0, 21.1],
            "high": [11.5, 11.6, 21.5, 21.6],
            "low": [10.8, 11.0, 20.8, 21.0],
            "close": [11.2, 11.3, 21.2, 21.3],
            "volume": [1_500_000, 1_600_000, 2_500_000, 2_600_000],
            "amount": [16_800_000, 18_080_000, 53_000_000, 55_380_000],
        }
    ).to_csv(path, index=False)


def _write_raw_vendor_bars_legacy_comment(path: Path) -> None:
    """
    pd.DataFrame(
        {
            "璇佸埜浠ｇ爜": ["600010.SH", "600010.SH", "SZ000010", "SZ000010"],
            "浜ゆ槗鏃ユ湡": [20240102, 20240103, 20240102, 20240103],
            "寮€鐩樹环": [11.0, 11.1, 21.0, 21.1],
            "鏈€楂樹环": [11.5, 11.6, 21.5, 21.6],
            "鏈€浣庝环": [10.8, 11.0, 20.8, 21.0],
            "鏀剁洏浠?: [11.2, 11.3, 21.2, 21.3],
            "鎴愪氦閲?: [1_500_000, 1_600_000, 2_500_000, 2_600_000],
            "鎴愪氦棰?: [16_800_000, 18_080_000, 53_000_000, 55_380_000],
        }
    ).to_csv(path, index=False)


def _write_day_file(path: Path, *, symbol_base: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = struct.Struct("<IIIIIfII")
    rows = [
        record.pack(
            20240102,
            int(symbol_base * 100),
            int((symbol_base + 0.5) * 100),
            int((symbol_base - 0.2) * 100),
            int((symbol_base + 0.2) * 100),
            float((symbol_base + 0.2) * 1_000_000),
            1_000_000,
            0,
        ),
        record.pack(
            20240103,
            int((symbol_base + 0.2) * 100),
            int((symbol_base + 0.8) * 100),
            int((symbol_base + 0.1) * 100),
            int((symbol_base + 0.6) * 100),
            float((symbol_base + 0.6) * 1_100_000),
            1_100_000,
            0,
        ),
    ]
    path.write_bytes(b"".join(rows))
    """
    pd.DataFrame(
        {
            "symbol": ["600010.SH", "600010.SH", "SZ000010", "SZ000010"],
            "date": [20240102, 20240103, 20240102, 20240103],
            "open": [11.0, 11.1, 21.0, 21.1],
            "high": [11.5, 11.6, 21.5, 21.6],
            "low": [10.8, 11.0, 20.8, 21.0],
            "close": [11.2, 11.3, 21.2, 21.3],
            "volume": [1_500_000, 1_600_000, 2_500_000, 2_600_000],
            "amount": [16_800_000, 18_080_000, 53_000_000, 55_380_000],
        }
    ).to_csv(path, index=False)
