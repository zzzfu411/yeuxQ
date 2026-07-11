"""Guarded one-command pipeline for the first-million research objective."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quantify.data.acquisition_plan import (
    build_recent_data_acquisition_plan_from_config,
    write_recent_data_acquisition_plan,
)
from quantify.data.cache_metadata import (
    build_promotion_metadata_check,
    write_promotion_metadata_check,
)
from quantify.data.csv_intake_preview import build_csv_intake_preview, write_csv_intake_preview
from quantify.data.evidence_packet import (
    build_data_evidence_action_packet,
    build_operator_handoff_status,
    write_data_evidence_action_packet,
)
from quantify.data.export_request import build_data_export_request, write_data_export_request
from quantify.data.gap_action_plan import build_data_gap_action_plan, write_data_gap_action_plan
from quantify.data.intake_router import build_data_intake_router, write_data_intake_router
from quantify.data.offline_intake import run_offline_data_intake
from quantify.data.offline_package import (
    build_offline_data_package_report,
    format_source_provenance,
    write_offline_data_package_report,
)
from quantify.data.ohlcv_experiment_package import (
    build_ohlcv_experiment_package_preflight,
    write_ohlcv_experiment_package_preflight,
)
from quantify.data.ohlcv_intake_closeout import run_ohlcv_intake_closeout
from quantify.data.provider import DataProvider
from quantify.data.provider_smoke_readiness import (
    build_provider_smoke_readiness,
    write_provider_smoke_readiness,
)
from quantify.data.raw_bars_discovery import (
    build_raw_bars_discovery_report,
    write_raw_bars_discovery_report,
)
from quantify.data.real_data_batch_onboarding import (
    build_real_data_batch_onboarding,
    write_real_data_batch_onboarding,
)
from quantify.data.real_data_handoff import (
    build_real_data_handoff_checklist,
    write_real_data_handoff_checklist,
)
from quantify.data.source_qa import (
    build_data_source_qa,
    build_data_source_qa_answers,
    build_data_source_qa_answers_from_evidence_worksheet,
    build_data_source_qa_evidence_worksheet_preflight,
    build_data_source_qa_review,
    write_data_source_qa,
    write_data_source_qa_answers,
    write_data_source_qa_evidence_worksheet_preflight,
    write_data_source_qa_review,
)
from quantify.data.source_qa_closeout import build_source_qa_closeout, write_source_qa_closeout
from quantify.data.source_qa_evidence_inbox import (
    build_source_qa_evidence_inbox,
    write_source_qa_evidence_inbox,
)
from quantify.data.source_qa_operator_packet import (
    build_source_qa_operator_packet,
    write_source_qa_evidence_dropzone_kit,
    write_source_qa_operator_packet,
)
from quantify.data.source_qa_preflight import build_source_qa_preflight, write_source_qa_preflight
from quantify.data.source_qa_readiness import (
    build_source_qa_evidence_readiness,
    write_source_qa_evidence_readiness,
)
from quantify.data.storage import BarStorage
from quantify.data.tdx_day import export_tdx_day_to_csv
from quantify.data.tdx_discovery import (
    build_tdx_day_discovery_report,
    write_tdx_day_discovery_report,
)
from quantify.data.tdx_source_qa import (
    build_tdx_source_qa_answers,
    write_tdx_source_qa_answers,
    write_tdx_source_qa_support_artifacts,
)
from quantify.data.vendor_bars_normalizer import (
    normalize_vendor_bars,
    write_vendor_bars_normalization_report,
)
from quantify.goal import CapitalGoal, build_capital_goal_status, write_capital_goal_status
from quantify.goal.compounding import build_compounding_path_review, write_compounding_path_review
from quantify.goal.status import _evaluate_cache_gate
from quantify.market import (
    build_market_context_operator_packet,
    build_market_context_readiness_from_payload,
    build_market_index_discovery_report,
    write_market_context_operator_packet,
    write_market_context_readiness,
    write_market_index_discovery_report,
)
from quantify.ops.data_intake_status import build_data_intake_status, write_data_intake_status
from quantify.ops.evidence_intake_kit import build_evidence_intake_kit, write_evidence_intake_kit
from quantify.ops.evidence_work_order import build_evidence_work_order, write_evidence_work_order
from quantify.ops.first_million_daily_brief import (
    build_first_million_daily_brief,
    write_first_million_daily_brief,
)
from quantify.ops.first_million_evidence_ranking_dashboard import (
    build_first_million_evidence_ranking_dashboard,
    write_first_million_evidence_ranking_dashboard,
)
from quantify.ops.first_million_readiness import (
    build_first_million_readiness_card,
    write_first_million_readiness_card,
)
from quantify.ops.first_million_resolution import (
    build_first_million_resolution_plan,
    write_first_million_resolution_plan,
)
from quantify.ops.pipeline import run_weekly_pipeline
from quantify.ops.run_manifest import build_run_manifest, write_run_manifest
from quantify.ops.strategy_brief import (
    build_first_million_strategy_brief,
    write_first_million_strategy_brief,
)
from quantify.ops.strategy_discovery_plan import (
    build_strategy_discovery_plan,
    write_strategy_discovery_plan,
)
from quantify.research.candidate_experiment_completion import (
    build_candidate_experiment_completion,
    write_candidate_experiment_completion,
)
from quantify.research.candidate_experiment_design import (
    build_candidate_experiment_design_matrix,
    write_candidate_experiment_design_matrix,
)
from quantify.research.candidate_experiment_execution import (
    PROHIBITED_ACTIONS as CANDIDATE_EXECUTION_PROHIBITED_ACTIONS,
)
from quantify.research.candidate_experiment_execution import (
    CandidateExperimentExecutionReport,
    run_candidate_experiment_execution,
    write_candidate_experiment_execution,
)
from quantify.research.candidate_experiment_launch import (
    build_candidate_experiment_launch,
    write_candidate_experiment_launch,
)
from quantify.research.candidate_experiment_queue import (
    build_candidate_experiment_queue,
    write_candidate_experiment_queue,
)
from quantify.research.candidate_experiment_readiness import (
    build_candidate_experiment_readiness,
    write_candidate_experiment_readiness,
)
from quantify.research.candidate_experiment_run_packet import (
    build_candidate_experiment_run_packet,
    write_candidate_experiment_run_packet,
)
from quantify.research.candidate_hypotheses import (
    build_candidate_hypothesis_catalog,
    write_candidate_hypothesis_catalog,
)
from quantify.utils.config import load_config

FirstMillionStatus = Literal["PASS", "WATCH", "BLOCK", "SKIPPED"]


@dataclass(frozen=True, slots=True)
class FirstMillionPipelineStage:
    name: str
    status: FirstMillionStatus
    artifact: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "artifact": self.artifact,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class FirstMillionPipelineResult:
    decision: Literal["PASS", "WATCH", "BLOCK"]
    output_dir: str
    data_dir: str
    config_path: str
    goal: dict[str, float | int]
    stages: list[FirstMillionPipelineStage]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "output_dir": self.output_dir,
            "data_dir": self.data_dir,
            "config_path": self.config_path,
            "goal": self.goal,
            "stages": [stage.to_dict() for stage in self.stages],
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# First Million Pipeline: {self.decision}",
            "",
            f"- Output directory: `{self.output_dir}`",
            f"- Data directory: `{self.data_dir}`",
            f"- Config: `{self.config_path}`",
            f"- Starting capital: {float(self.goal['starting_capital']):.2f}",
            f"- Target capital: {float(self.goal['target_capital']):.2f}",
            f"- Horizon years: {float(self.goal['years']):.1f}",
            f"- Required annual return: {float(self.goal['required_annual_return']):.2%}",
            "",
            "## Stages",
            "",
            "| stage | status | artifact | message |",
            "| --- | --- | --- | --- |",
        ]
        for stage in self.stages:
            lines.append(
                f"| `{stage.name}` | `{stage.status}` | `{stage.artifact}` | {stage.message} |"
            )
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class SourceQAAnswersProvenance:
    mode: str
    answers_path: str
    input_path: str
    input_sha256: str
    checklist_path: str
    checklist_sha256: str
    generated_by: str
    message: str
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "answers_path": self.answers_path,
            "input_path": self.input_path,
            "input_sha256": self.input_sha256,
            "checklist_path": self.checklist_path,
            "checklist_sha256": self.checklist_sha256,
            "generated_by": self.generated_by,
            "message": self.message,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Source QA Answers Provenance",
            "",
            f"- Mode: `{self.mode}`",
            f"- Answers: `{self.answers_path}`",
            f"- Input: `{self.input_path}`",
            f"- Input sha256: `{self.input_sha256}`",
            f"- Checklist: `{self.checklist_path}`",
            f"- Checklist sha256: `{self.checklist_sha256}`",
            f"- Generated by: `{self.generated_by}`",
            "",
            self.message,
            "",
            "## Prohibited Actions",
        ]
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def run_first_million_pipeline(
    *,
    config_path: str | Path = "config/research_recent.yaml",
    cache_path: str | Path | None = None,
    data_dir: str | Path = "data_exports",
    output_dir: str | Path = "results/first_million",
    source_qa_answers: str | Path | None = None,
    source_qa_worksheet: str | Path | None = None,
    source_qa_evidence_manifest: str | Path | None = None,
    require_source_qa_evidence_manifest: bool = False,
    starting_capital: float = 100_000.0,
    target_capital: float = 1_000_000.0,
    years: float = 8.0,
    max_drawdown_budget: float = 0.20,
    min_symbols: int = 300,
    min_trading_days: int = 240,
    as_of: str | None = None,
    encoding: str = "utf-8-sig",
    raw_bars_csv: str | Path | None = None,
    source_vendor: str | None = None,
    source_terminal: str | None = None,
    source_operator: str | None = None,
    source_exported_at: str | None = None,
    source_price_adjustment: str | None = None,
    source_price_adjustment_evidence: str | None = None,
    source_license_scope: str = "research and paper trading only",
    source_license_evidence: str | None = None,
    source_point_in_time_evidence: str | None = None,
    source_reviewed_by: str | None = None,
    source_reviewed_at: str | None = None,
    source_known_limitations: str = "",
    paper_state_dir: str | Path | None = None,
    prepare_micro_live_readiness: bool = False,
    micro_live_candidate: str | None = None,
    micro_live_capital: float | None = None,
    micro_live_cash_buffer_pct: float = 0.05,
    current_positions_path: str | Path | None = None,
    registry_path: str | Path | None = "results/strategy_registry/strategy_registry.json",
    latest_import_report_path: str | Path | None = "results/import/recent/data_import.json",
    provider_acquisition_ramp_report_path: str | Path | None = None,
    tdx_search_dirs: list[str | Path] | None = None,
    tdx_input_dir: str | Path | None = None,
    tdx_operator: str | None = None,
    tdx_exported_at: str | None = None,
    tdx_price_adjustment: str | None = None,
    tdx_price_adjustment_evidence: str | None = None,
    tdx_license_scope: str = "research and paper trading only",
    tdx_license_evidence: str | None = None,
    tdx_pit_fundamental_evidence: str | None = None,
    tdx_reviewed_by: str | None = None,
    tdx_reviewed_at: str | None = None,
    tdx_known_limitations: str = "",
    execute_candidate_experiment: bool = False,
) -> FirstMillionPipelineResult:
    """Run the guarded first-million pipeline.

    The function never connects to a broker and never submits live orders. It
    stops before weekly strategy research unless source QA and offline intake
    both pass.
    """
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    data_root = Path(data_dir)
    cfg = load_config(config_path)
    if cache_path is not None:
        payload = cfg.to_dict()
        data = dict(payload.get("data", {}))
        data["cache_path"] = str(cache_path)
        cfg = type(cfg)({**payload, "data": data})
    resolved_cache_path = Path(str(cfg.data.cache_path))
    storage: BarStorage | None = None
    provider: DataProvider | None = None

    def _load_cache_provider() -> tuple[BarStorage, DataProvider]:
        nonlocal storage, provider
        if storage is None or provider is None:
            storage = BarStorage(resolved_cache_path)
            provider = DataProvider(storage)
        return storage, provider
    goal = CapitalGoal(
        starting_capital=starting_capital,
        target_capital=target_capital,
        years=years,
        max_drawdown_budget=max_drawdown_budget,
    )
    stages: list[FirstMillionPipelineStage] = []
    source_answers_provenance: SourceQAAnswersProvenance | None = None
    source_qa_dir = root / "source_qa"

    answers_path = Path(source_qa_answers) if source_qa_answers else data_root / "data_source_qa_answers.json"
    worksheet_path = Path(source_qa_worksheet) if source_qa_worksheet else None
    evidence_manifest_path = (
        Path(source_qa_evidence_manifest)
        if source_qa_evidence_manifest
        else data_root / "source_qa_evidence_manifest.json"
    )
    review_evidence_manifest_path = (
        evidence_manifest_path
        if (
            source_qa_evidence_manifest is not None
            or require_source_qa_evidence_manifest
            or evidence_manifest_path.exists()
        )
        else None
    )
    source_qa_worksheet_rows = _read_text_if_exists(worksheet_path)
    resolved_tdx_search_dirs = _tdx_search_dirs(tdx_input_dir, tdx_search_dirs)
    ambiguous_data_inputs = raw_bars_csv is not None and tdx_input_dir is not None
    intake_raw_bars_csv = None if ambiguous_data_inputs else raw_bars_csv
    tdx_source_fields = {
        "tdx_operator": tdx_operator,
        "tdx_exported_at": tdx_exported_at,
        "tdx_price_adjustment_evidence": tdx_price_adjustment_evidence,
        "tdx_license_evidence": tdx_license_evidence,
        "tdx_reviewed_by": tdx_reviewed_by,
        "tdx_reviewed_at": tdx_reviewed_at,
    }
    has_tdx_source_fields = any(value is not None for value in tdx_source_fields.values())
    tdx_discovery = None

    hypothesis_catalog = build_candidate_hypothesis_catalog(cfg, as_of=as_of)
    write_candidate_hypothesis_catalog(hypothesis_catalog, root)
    stages.append(
        FirstMillionPipelineStage(
            "candidate_hypotheses",
            "PASS",
            str(root / "candidate_hypotheses.json"),
            "Research-only strategy hypothesis catalog is available.",
        )
    )

    experiment_queue = build_candidate_experiment_queue(cfg, as_of=as_of, catalog=hypothesis_catalog)
    write_candidate_experiment_queue(experiment_queue, root)
    stages.append(
        FirstMillionPipelineStage(
            "candidate_experiment_queue",
            "PASS",
            str(root / "candidate_experiment_queue.json"),
            "Pre-registered research experiment queue is available.",
        )
    )
    experiment_design = build_candidate_experiment_design_matrix(
        cfg,
        as_of=as_of,
        queue=experiment_queue,
    )
    write_candidate_experiment_design_matrix(experiment_design, root)
    stages.append(
        FirstMillionPipelineStage(
            "candidate_experiment_design_matrix",
            "PASS",
            str(root / "candidate_experiment_design_matrix.json"),
            _experiment_design_message(experiment_design.to_dict()),
        )
    )

    acquisition_plan = build_recent_data_acquisition_plan_from_config(
        config_path=config_path,
        cache_path=cache_path,
        as_of=as_of,
        min_symbols=min_symbols,
        import_limit=max(min_symbols, 500),
        latest_import_report_path=latest_import_report_path,
    )
    write_recent_data_acquisition_plan(acquisition_plan, root)
    stages.append(
        FirstMillionPipelineStage(
            "recent_data_acquisition_plan",
            acquisition_plan.status,
            str(root / "recent_data_acquisition_plan.json"),
            _acquisition_message(acquisition_plan.to_dict()),
        )
    )
    provider_smoke = build_provider_smoke_readiness(
        latest_import_report_path=latest_import_report_path,
        requested_end=str(cfg.research.end),
        provider="akshare",
        as_of=as_of,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
    )
    write_provider_smoke_readiness(provider_smoke, root)
    stages.append(
        FirstMillionPipelineStage(
            "provider_smoke_readiness",
            _provider_smoke_stage_status(provider_smoke.to_dict()),
            str(root / "provider_smoke_readiness.json"),
            _provider_smoke_message(provider_smoke.to_dict()),
        )
    )
    provider_ramp_payload = _copy_provider_acquisition_ramp_report(
        provider_acquisition_ramp_report_path,
        root,
    )
    if provider_ramp_payload:
        stages.append(
            FirstMillionPipelineStage(
                "provider_acquisition_ramp",
                _provider_ramp_stage_status(provider_ramp_payload),
                str(root / "provider_acquisition_ramp.json"),
                _provider_ramp_message(provider_ramp_payload),
            )
        )

    export_request = build_data_export_request(
        config_path=config_path,
        output_dir=data_root,
        min_symbols=min_symbols,
    )
    write_data_export_request(export_request, data_root)
    stages.append(
        FirstMillionPipelineStage(
            "data_export_request",
            "PASS",
            str(data_root / "data_export_request.json"),
            "Vendor-facing export request is available.",
        )
    )

    if ambiguous_data_inputs:
        stages.append(
            FirstMillionPipelineStage(
                "data_source_selection",
                "BLOCK",
                str(root / "first_million_pipeline.json"),
                "Choose exactly one local data input: --raw-bars-csv or --tdx-input-dir, not both.",
            )
        )
    elif raw_bars_csv is not None:
        normalization = normalize_vendor_bars(
            input_path=raw_bars_csv,
            output_dir=data_root,
            encoding=encoding,
            start=str(cfg.research.start),
            end=str(cfg.research.end),
            min_symbols=min_symbols,
        )
        write_vendor_bars_normalization_report(normalization, root)
        stages.append(
            FirstMillionPipelineStage(
                "vendor_bars_normalization",
                normalization.status,
                str(root / "vendor_bars_normalization.json"),
                _normalization_message(normalization.to_dict()),
            )
        )
    elif tdx_input_dir is not None:
        tdx_discovery = build_tdx_day_discovery_report(
            search_dirs=[tdx_input_dir],
            config_path=config_path,
            output_dir=root,
            data_output_dir=data_root,
            min_symbols=min_symbols,
            start=str(cfg.research.start),
            end=str(cfg.research.end),
            as_of=as_of,
        )
        if tdx_discovery.status == "BLOCK":
            stages.append(
                FirstMillionPipelineStage(
                    "tdx_day_export",
                    "BLOCK",
                    str(data_root / "tdx_day_export.json"),
                    _tdx_export_skipped_message(tdx_discovery.to_dict()),
                )
            )
        else:
            tdx_export = export_tdx_day_to_csv(
                input_dir=tdx_input_dir,
                output_dir=data_root,
                start=str(cfg.research.start),
                end=str(cfg.research.end),
            )
            stages.append(
                FirstMillionPipelineStage(
                    "tdx_day_export",
                    tdx_export.status,
                    str(data_root / "tdx_day_export.json"),
                    _tdx_export_message(tdx_export.to_dict()),
            )
        )
    raw_bars_search_dirs = [Path(raw_bars_csv)] if raw_bars_csv is not None else [data_root / "raw", data_root]
    raw_bars_discovery = build_raw_bars_discovery_report(
        search_dirs=raw_bars_search_dirs,
        config_path=config_path,
        output_dir=root,
        data_output_dir=data_root,
        min_symbols=min_symbols,
        start=str(cfg.research.start),
        end=str(cfg.research.end),
        encoding=encoding if encoding else "auto",
    )
    write_raw_bars_discovery_report(raw_bars_discovery, root)
    stages.append(
        FirstMillionPipelineStage(
            "raw_bars_discovery",
            raw_bars_discovery.status,
            str(root / "raw_bars_discovery.json"),
            _raw_bars_discovery_message(raw_bars_discovery.to_dict()),
        )
    )

    checklist = build_data_source_qa(
        config_path=config_path,
        output_dir=data_root,
        min_symbols=min_symbols,
        as_of=as_of,
    )
    write_data_source_qa(checklist, data_root)
    checklist_path = data_root / "data_source_qa.json"
    stages.append(
        FirstMillionPipelineStage(
            "data_source_qa",
            "PASS",
            str(checklist_path),
            "Source QA checklist and answer template are available.",
        )
    )
    source_fields = {
        "source_vendor": source_vendor,
        "source_terminal": source_terminal,
        "source_operator": source_operator,
        "source_exported_at": source_exported_at,
        "source_price_adjustment": source_price_adjustment,
        "source_price_adjustment_evidence": source_price_adjustment_evidence,
        "source_license_evidence": source_license_evidence,
        "source_point_in_time_evidence": source_point_in_time_evidence,
        "source_reviewed_by": source_reviewed_by,
        "source_reviewed_at": source_reviewed_at,
    }
    has_generic_source_fields = any(value is not None for value in source_fields.values())
    has_worksheet_source = worksheet_path is not None
    source_mode_count = sum(
        1 for enabled in (has_generic_source_fields, has_tdx_source_fields, has_worksheet_source) if enabled
    )
    if source_mode_count > 1:
        stages.append(
            FirstMillionPipelineStage(
                "source_qa_answers",
                "BLOCK",
                str(answers_path),
                "Choose exactly one source QA evidence path, not both/multiple: "
                "--source-qa-worksheet, generic --source-* fields, or TDX-specific --tdx-* fields.",
            )
        )
    elif has_worksheet_source:
        if not worksheet_path.exists():
            stages.append(
                FirstMillionPipelineStage(
                    "source_qa_answers",
                    "BLOCK",
                    str(answers_path),
                    f"Filled source QA worksheet is missing: {worksheet_path}",
                )
            )
        else:
            worksheet_preflight = build_data_source_qa_evidence_worksheet_preflight(
                checklist_path=checklist_path,
                worksheet_path=worksheet_path,
                encoding=encoding,
                worksheet_text=source_qa_worksheet_rows,
            )
            write_data_source_qa_evidence_worksheet_preflight(worksheet_preflight, source_qa_dir)
            stages.append(
                FirstMillionPipelineStage(
                    "source_qa_worksheet_preflight",
                    worksheet_preflight.status,
                    str(source_qa_dir / "data_source_qa_worksheet_preflight.json"),
                    _worksheet_preflight_message(worksheet_preflight.to_dict()),
                )
            )
            if worksheet_preflight.status == "BLOCK":
                stages.append(
                    FirstMillionPipelineStage(
                        "source_qa_answers",
                        "BLOCK",
                        str(answers_path),
                        "Source QA worksheet preflight is BLOCK; fix the worksheet before generating answers.",
                    )
                )
            else:
                answers = build_data_source_qa_answers_from_evidence_worksheet(
                    checklist_path=checklist_path,
                    worksheet_path=worksheet_path,
                    encoding=encoding,
                    worksheet_text=source_qa_worksheet_rows,
                )
                write_data_source_qa_answers(answers, answers_path)
                source_answers_provenance = _source_answers_provenance(
                    mode="worksheet",
                    answers_path=answers_path,
                    input_path=worksheet_path,
                    checklist_path=checklist_path,
                    generated_by="run_first_million_pipeline --source-qa-worksheet",
                    message=(
                        "Source QA answers were generated from a filled evidence worksheet after "
                        "worksheet preflight; deterministic source QA review still decides validity."
                    ),
                )
                write_source_qa_answers_provenance(source_answers_provenance, root)
                stages.append(
                    FirstMillionPipelineStage(
                        "source_qa_answers",
                        "PASS",
                        str(answers_path),
                        "Wrote source QA answers from a worksheet that passed preflight; source review still decides validity.",
                    )
                )
    elif has_tdx_source_fields:
        missing = [name for name, value in tdx_source_fields.items() if not str(value or "").strip()]
        if tdx_input_dir is None:
            missing.append("tdx_input_dir")
        if missing:
            stages.append(
                FirstMillionPipelineStage(
                    "source_qa_answers",
                    "BLOCK",
                    str(answers_path),
                    f"Missing required TDX source QA fields: {', '.join(missing)}",
                )
            )
        else:
            answers = build_tdx_source_qa_answers(
                checklist_path=checklist_path,
                tdx_export_report=data_root / "tdx_day_export.json",
                input_dir=tdx_input_dir,
                export_operator=str(tdx_operator),
                exported_at_local_time=str(tdx_exported_at),
                price_adjustment=tdx_price_adjustment,
                price_adjustment_evidence=str(tdx_price_adjustment_evidence),
                license_or_usage_scope=tdx_license_scope,
                license_evidence=str(tdx_license_evidence),
                pit_fundamental_evidence=tdx_pit_fundamental_evidence,
                reviewed_by=str(tdx_reviewed_by),
                reviewed_at=str(tdx_reviewed_at),
                encoding=encoding,
                known_limitations=tdx_known_limitations,
            )
            write_tdx_source_qa_answers(answers, answers_path)
            write_tdx_source_qa_support_artifacts(
                answers,
                checklist_path=checklist_path,
                worksheet_path=data_root / "data_source_qa_evidence_worksheet.csv",
                evidence_dir=data_root / "source_qa_evidence",
                manifest_path=evidence_manifest_path,
                encoding=encoding,
            )
            input_snapshot = _write_source_answers_input_snapshot(
                root,
                mode="tdx_fields",
                fields={
                    **tdx_source_fields,
                    "tdx_input_dir": str(tdx_input_dir),
                    "tdx_price_adjustment": tdx_price_adjustment,
                    "tdx_license_scope": tdx_license_scope,
                    "tdx_pit_fundamental_evidence": tdx_pit_fundamental_evidence,
                    "tdx_known_limitations": tdx_known_limitations,
                },
            )
            source_answers_provenance = _source_answers_provenance(
                mode="tdx_fields",
                answers_path=answers_path,
                input_path=input_snapshot,
                checklist_path=checklist_path,
                generated_by="run_first_million_pipeline --tdx-* source evidence fields",
                message="Source QA answers were generated from explicit TDX OHLCV evidence fields; deterministic preflight and source review still decide validity.",
            )
            write_source_qa_answers_provenance(source_answers_provenance, root)
            stages.append(
                FirstMillionPipelineStage(
                    "source_qa_answers",
                    "PASS",
                    str(answers_path),
                    "Wrote TDX OHLCV-only source QA answers from explicit user-supplied evidence fields.",
                )
            )
    elif has_generic_source_fields:
        missing = [name for name, value in source_fields.items() if not str(value or "").strip()]
        if missing:
            stages.append(
                FirstMillionPipelineStage(
                    "source_qa_answers",
                    "BLOCK",
                    str(answers_path),
                    f"Missing required source QA answer fields: {', '.join(missing)}",
                )
            )
        else:
            answers = build_data_source_qa_answers(
                checklist_path=checklist_path,
                data_vendor_or_broker=str(source_vendor),
                terminal_or_product_name=str(source_terminal),
                export_operator=str(source_operator),
                exported_at_local_time=str(source_exported_at),
                price_adjustment=str(source_price_adjustment),
                price_adjustment_evidence=str(source_price_adjustment_evidence),
                license_or_usage_scope=source_license_scope,
                license_evidence=str(source_license_evidence),
                point_in_time_evidence=str(source_point_in_time_evidence),
                reviewed_by=str(source_reviewed_by),
                reviewed_at=str(source_reviewed_at),
                encoding=encoding,
                known_limitations=source_known_limitations,
            )
            write_data_source_qa_answers(answers, answers_path)
            input_snapshot = _write_source_answers_input_snapshot(
                root,
                mode="explicit_fields",
                fields={
                    **source_fields,
                    "source_license_scope": source_license_scope,
                    "source_known_limitations": source_known_limitations,
                },
            )
            source_answers_provenance = _source_answers_provenance(
                mode="explicit_fields",
                answers_path=answers_path,
                input_path=input_snapshot,
                checklist_path=checklist_path,
                generated_by="run_first_million_pipeline --source-* evidence fields",
                message="Source QA answers were generated from explicit source evidence fields; deterministic preflight and source review still decide validity.",
            )
            write_source_qa_answers_provenance(source_answers_provenance, root)
            stages.append(
                FirstMillionPipelineStage(
                    "source_qa_answers",
                    "PASS",
                    str(answers_path),
                    "Wrote source QA answers from explicit user-supplied evidence fields.",
                )
            )
    if source_answers_provenance is not None:
        stages.append(
            FirstMillionPipelineStage(
                "source_qa_answers_provenance",
                "PASS",
                str(root / "source_qa_answers_provenance.json"),
                source_answers_provenance.message,
            )
        )

    data_gap_plan = build_data_gap_action_plan(
        data_dir=data_root,
        config_path=config_path,
        source_qa_answers=answers_path,
        min_symbols=min_symbols,
        as_of=as_of,
        encoding=encoding,
    )
    write_data_gap_action_plan(data_gap_plan, root)
    stages.append(
        FirstMillionPipelineStage(
            "data_gap_action_plan",
            data_gap_plan.decision,
            str(root / "data_gap_action_plan.json"),
            _gap_plan_message(data_gap_plan.to_dict()),
        )
    )
    data_evidence_packet = build_data_evidence_action_packet(
        data_dir=data_root,
        config_path=config_path,
        source_qa_answers=answers_path,
        min_symbols=min_symbols,
        as_of=as_of,
        encoding=encoding,
        data_gap_plan=data_gap_plan,
        export_request=export_request,
    )
    write_data_evidence_action_packet(data_evidence_packet, root)
    source_qa_operator_packet = build_source_qa_operator_packet(
        data_dir=data_root,
        report_dir=root,
        as_of=as_of,
    )
    write_source_qa_operator_packet(source_qa_operator_packet, root)
    write_source_qa_evidence_dropzone_kit(source_qa_operator_packet)
    source_qa_evidence_inbox = build_source_qa_evidence_inbox(
        data_dir=data_root,
        report_dir=root,
        checklist_path=checklist_path,
        evidence_dir=data_root / "source_qa_evidence",
        manifest_path=evidence_manifest_path,
        as_of=as_of,
    )
    write_source_qa_evidence_inbox(source_qa_evidence_inbox, root)
    evidence_intake_kit = build_evidence_intake_kit(
        report_dir=root,
        data_dir=data_root,
        as_of=as_of,
    )
    write_evidence_intake_kit(evidence_intake_kit)
    evidence_work_order = build_evidence_work_order(
        report_dir=root,
        data_dir=data_root,
        as_of=as_of,
    )
    write_evidence_work_order(evidence_work_order, root)
    operator_handoff_status = build_operator_handoff_status(
        packet=data_evidence_packet,
        operator_handoff_path=root / "operator_handoff.csv",
    )
    stages.append(
        FirstMillionPipelineStage(
            "data_evidence_action_packet",
            data_evidence_packet.decision,
            str(root / "data_evidence_action_packet.json"),
            _data_evidence_packet_message(data_evidence_packet.to_dict()),
        )
    )
    stages.append(
        FirstMillionPipelineStage(
            "operator_handoff_status",
            operator_handoff_status.status,
            str(root / "operator_handoff_status.json"),
            _operator_handoff_status_message(operator_handoff_status.to_dict()),
        )
    )
    stages.append(
        FirstMillionPipelineStage(
            "source_qa_evidence_inbox",
            source_qa_evidence_inbox.status,
            str(root / "source_qa_evidence_inbox.json"),
            _source_qa_evidence_inbox_message(source_qa_evidence_inbox.to_dict()),
        )
    )
    stages.append(
        FirstMillionPipelineStage(
            "evidence_intake_kit",
            evidence_intake_kit.decision,
            str(Path(evidence_intake_kit.kit_dir) / "first_million_evidence_intake_kit.json"),
            _evidence_intake_kit_message(evidence_intake_kit.to_dict()),
        )
    )
    stages.append(
        FirstMillionPipelineStage(
            "evidence_work_order",
            evidence_work_order.decision,
            str(root / "first_million_evidence_work_order.json"),
            _evidence_work_order_message(evidence_work_order.to_dict()),
        )
    )
    csv_intake_preview = build_csv_intake_preview(
        data_dir=data_root,
        encoding=encoding,
    )
    write_csv_intake_preview(csv_intake_preview, root)
    stages.append(
        FirstMillionPipelineStage(
            "csv_intake_preview",
            csv_intake_preview.status,
            str(root / "csv_intake_preview.json"),
            _csv_intake_preview_message(csv_intake_preview.to_dict()),
        )
    )

    source_preflight = build_source_qa_preflight(
        checklist_path=checklist_path,
        answers_path=answers_path,
        evidence_manifest_path=review_evidence_manifest_path,
        require_evidence_manifest=require_source_qa_evidence_manifest,
        output_dir=source_qa_dir,
    )
    write_source_qa_preflight(source_preflight, source_qa_dir)
    stages.append(
        FirstMillionPipelineStage(
            "source_qa_preflight",
            source_preflight.status,
            str(source_qa_dir / "source_qa_preflight.json"),
            _source_preflight_message(source_preflight.to_dict()),
        )
    )

    if tdx_discovery is None:
        tdx_discovery = build_tdx_day_discovery_report(
            search_dirs=resolved_tdx_search_dirs,
            config_path=config_path,
            output_dir=root,
            data_output_dir=data_root,
            min_symbols=min_symbols,
            start=str(cfg.research.start),
            end=str(cfg.research.end),
            as_of=as_of,
        )

    data_intake_router = build_data_intake_router(
        data_dir=data_root,
        config_path=config_path,
        source_qa_answers=answers_path,
        source_qa_evidence_manifest=review_evidence_manifest_path,
        require_source_qa_evidence_manifest=require_source_qa_evidence_manifest,
        latest_import_report_path=latest_import_report_path,
        tdx_search_dirs=resolved_tdx_search_dirs,
        tdx_discovery=tdx_discovery,
        min_symbols=min_symbols,
        as_of=as_of,
        encoding=encoding,
    )
    write_data_intake_router(data_intake_router, root)
    stages.append(
        FirstMillionPipelineStage(
            "data_intake_router",
            data_intake_router.status,
            str(root / "data_intake_router.json"),
            _data_intake_router_message(data_intake_router.to_dict()),
        )
    )

    write_tdx_day_discovery_report(tdx_discovery, root)
    stages.append(
        FirstMillionPipelineStage(
            "tdx_day_discovery",
            tdx_discovery.status,
            str(root / "tdx_day_discovery.json"),
            _tdx_discovery_message(tdx_discovery.to_dict()),
        )
    )

    offline_package = build_offline_data_package_report(
        data_dir=data_root,
        config_path=config_path,
        source_qa_answers=answers_path,
        source_qa_evidence_manifest=review_evidence_manifest_path,
        require_source_qa_evidence_manifest=require_source_qa_evidence_manifest,
        min_symbols=min_symbols,
        as_of=as_of,
        encoding=encoding,
    )
    write_offline_data_package_report(offline_package, root)
    stages.append(
        FirstMillionPipelineStage(
            "offline_data_package",
            offline_package.status,
            str(root / "offline_data_package.json"),
            _offline_package_message(offline_package.to_dict()),
        )
    )

    real_data_handoff = build_real_data_handoff_checklist(
        data_dir=data_root,
        config_path=config_path,
        source_qa_answers=answers_path,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
        as_of=as_of,
        encoding=encoding,
        data_gap_plan=data_gap_plan,
        offline_package=offline_package,
    )
    write_real_data_handoff_checklist(real_data_handoff, root)
    stages.append(
        FirstMillionPipelineStage(
            "real_data_handoff_checklist",
            real_data_handoff.status,
            str(root / "real_data_handoff_checklist.json"),
            _handoff_message(real_data_handoff.to_dict()),
        )
    )

    source_review = build_data_source_qa_review(
        checklist_path=checklist_path,
        answers_path=answers_path,
        evidence_manifest_path=review_evidence_manifest_path,
        require_evidence_manifest=require_source_qa_evidence_manifest,
    )
    write_data_source_qa_review(source_review, source_qa_dir)
    stages.append(
        FirstMillionPipelineStage(
            "data_source_qa_review",
            source_review.status,
            str(source_qa_dir / "data_source_qa_review.json"),
            _review_message(source_review.to_dict()),
        )
    )

    source_qa_readiness = build_source_qa_evidence_readiness(
        checklist_path=checklist_path,
        worksheet_path=data_root / "data_source_qa_evidence_worksheet.csv",
        answers_path=answers_path,
        evidence_manifest_path=evidence_manifest_path,
        review_artifact_path=source_qa_dir / "data_source_qa_review.json",
        evidence_dir=data_root / "source_qa_evidence",
        require_evidence_manifest=require_source_qa_evidence_manifest,
        encoding=encoding,
    )
    write_source_qa_evidence_readiness(source_qa_readiness, source_qa_dir)
    stages.append(
        FirstMillionPipelineStage(
            "source_qa_evidence_readiness",
            source_qa_readiness.status,
            str(source_qa_dir / "source_qa_evidence_readiness.json"),
            _source_qa_evidence_readiness_message(source_qa_readiness.to_dict()),
        )
    )
    source_qa_closeout = build_source_qa_closeout(
        data_dir=data_root,
        report_dir=root,
        checklist_path=checklist_path,
        worksheet_path=data_root / "data_source_qa_evidence_worksheet.csv",
        answers_path=answers_path,
        evidence_dir=data_root / "source_qa_evidence",
        evidence_manifest_path=evidence_manifest_path,
        require_evidence_manifest=require_source_qa_evidence_manifest,
        as_of=as_of,
        encoding=encoding,
        operator_packet=source_qa_operator_packet,
        evidence_inbox=source_qa_evidence_inbox,
        evidence_readiness=source_qa_readiness,
    )
    write_source_qa_closeout(source_qa_closeout, root)
    stages.append(
        FirstMillionPipelineStage(
            "source_qa_closeout",
            source_qa_closeout.decision,
            str(root / "source_qa_closeout.json"),
            _source_qa_closeout_message(source_qa_closeout.to_dict()),
        )
    )

    intake_dir = root / "offline_intake"
    ohlcv_closeout = run_ohlcv_intake_closeout(
        raw_bars_csv=intake_raw_bars_csv,
        data_dir=data_root,
        report_dir=root,
        config_path=config_path,
        cache_path=resolved_cache_path,
        source_qa_answers=answers_path,
        source_qa_evidence_manifest=evidence_manifest_path,
        require_source_qa_evidence_manifest=require_source_qa_evidence_manifest,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
        as_of=as_of,
        encoding=encoding,
        raw_bars_discovery=raw_bars_discovery,
    )
    stages.append(
        FirstMillionPipelineStage(
            "ohlcv_intake_closeout",
            ohlcv_closeout.decision,
            str(root / "ohlcv_intake_closeout.json"),
            _ohlcv_intake_closeout_message(ohlcv_closeout.to_dict()),
        )
    )
    data_intake_status = build_data_intake_status(
        report_dir=root,
        data_dir=data_root,
        as_of=as_of,
    )
    write_data_intake_status(data_intake_status, root)
    stages.append(
        FirstMillionPipelineStage(
            "data_intake_status",
            data_intake_status.decision,
            str(root / "data_intake_status.json"),
            _data_intake_status_message(data_intake_status.to_dict()),
        )
    )
    if ohlcv_closeout.offline_intake_report is not None:
        intake = ohlcv_closeout.offline_intake_report
    else:
        fallback_raw_bars_csv = (
            intake_raw_bars_csv
            if ohlcv_closeout.source_qa_status == "PASS"
            else None
        )
        intake = run_offline_data_intake(
            raw_bars_csv=fallback_raw_bars_csv,
            data_dir=data_root,
            config_path=config_path,
            output_dir=intake_dir,
            min_symbols=min_symbols,
            min_trading_days=min_trading_days,
            as_of=as_of,
            encoding=encoding,
            source_qa_checklist=checklist_path,
            source_qa_answers=answers_path,
            source_qa_evidence_manifest=evidence_manifest_path,
            require_source_qa_evidence_manifest=require_source_qa_evidence_manifest,
        )
    stages.append(
        FirstMillionPipelineStage(
            "offline_data_intake",
            intake.status,
            str(intake_dir / "offline_data_intake.json"),
            _intake_message(intake.to_dict()),
        )
    )

    promotion_metadata = build_promotion_metadata_check(
        resolved_cache_path,
        require_evidence_manifest=require_source_qa_evidence_manifest,
    )
    write_promotion_metadata_check(promotion_metadata, root)
    stages.append(
        FirstMillionPipelineStage(
            "promotion_metadata_check",
            promotion_metadata.status,
            str(root / "promotion_metadata_check.json"),
            _promotion_metadata_message(promotion_metadata.to_dict()),
        )
    )

    if intake.status != "BLOCK":
        storage, provider = _load_cache_provider()
        manifest = build_run_manifest(
            provider,
            cfg,
            storage=storage,
            config_path=config_path,
            purpose="first_million_offline_intake",
            demo_data_used=False,
        )
        write_run_manifest(manifest, root)
        stages.append(
            FirstMillionPipelineStage(
                "run_manifest",
                "PASS",
                str(root / "run_manifest.json"),
                _manifest_message(manifest.to_dict()),
            )
        )

    research_cache_gate = {
        "decision": "BLOCK",
        "latest_bar_date": "",
        "symbol_count": 0,
        "trading_day_count": 0,
        "bar_count": 0,
        "demo_data_used": False,
    }
    if resolved_cache_path.exists():
        _, provider = _load_cache_provider()
        research_cache_gate = _evaluate_cache_gate(
            provider,
            str(cfg.research.start),
            str(cfg.research.end),
            as_of=as_of,
            min_symbols=min_symbols,
            min_trading_days=min_trading_days,
        )
    allow_research_only_weekly = (
        intake.status != "PASS"
        and research_cache_gate["decision"] in {"PASS", "WATCH"}
        and not bool(research_cache_gate["demo_data_used"])
    )
    weekly_output_dir: Path | None = None

    if intake.status == "PASS" or allow_research_only_weekly:
        weekly = run_weekly_pipeline(
            cfg,
            config_path=config_path,
            output_dir=root / "weekly",
            starting_capital=starting_capital,
            target_capital=target_capital,
            years=years,
            max_drawdown_budget=max_drawdown_budget,
            review_stage=(
                "micro_live_ready"
                if prepare_micro_live_readiness
                else ("paper" if intake.status == "PASS" else "research")
            ),
            registry_path=registry_path,
            paper_state_dir=paper_state_dir,
            as_of=as_of,
            prepare_micro_live_readiness=prepare_micro_live_readiness,
            micro_live_candidate=micro_live_candidate,
            micro_live_capital=micro_live_capital,
            micro_live_cash_buffer_pct=micro_live_cash_buffer_pct,
            current_positions_path=current_positions_path,
        )
        weekly_output_dir = Path(weekly.output_dir)
        stages.append(
            FirstMillionPipelineStage(
                "weekly_pipeline",
                "PASS" if weekly.weekly_decision == "continue_paper" else "WATCH",
                str(Path(weekly.output_dir) / "weekly_pipeline.json"),
                (
                    f"Weekly decision={weekly.weekly_decision}."
                    if intake.status == "PASS"
                    else (
                        "Research-only weekly pipeline ran on admissible real cache; "
                        f"weekly decision={weekly.weekly_decision}. Source QA/offline intake still gate promotion."
                    )
                ),
            )
        )
    else:
        stages.append(
            FirstMillionPipelineStage(
                "weekly_pipeline",
                "SKIPPED",
                str(root / "weekly" / "weekly_pipeline.json"),
                "Skipped until either guarded offline intake passes or a recent real cache is admissible for research-only review.",
            )
        )
    if prepare_micro_live_readiness:
        if weekly_output_dir is None:
            stages.append(
                FirstMillionPipelineStage(
                    "micro_live_readiness",
                    "SKIPPED",
                    str(root / "weekly" / "micro_live_readiness.json"),
                    "Skipped because weekly evidence did not run; no broker orders or approvals were created.",
                )
            )
        else:
            target_payload = _read_json(weekly_output_dir / "target_portfolio.json")
            if target_payload:
                stages.append(
                    FirstMillionPipelineStage(
                        "manual_target_plan",
                        "PASS",
                        str(weekly_output_dir / "target_portfolio.json"),
                        _manual_target_plan_message(target_payload),
                    )
                )
            readiness_payload = _read_json(weekly_output_dir / "micro_live_readiness.json")
            stages.append(
                FirstMillionPipelineStage(
                    "micro_live_readiness",
                    _micro_live_readiness_stage_status(readiness_payload),
                    str(weekly_output_dir / "micro_live_readiness.json"),
                    _micro_live_readiness_message(readiness_payload),
                )
            )

    market_regime = _read_first_available_json(
        root / "market_regime.json",
        root / "weekly" / "market_regime.json",
    )
    market_context_snapshot = _read_json(root / "market_context_snapshot.json")
    market_index_discovery = build_market_index_discovery_report(
        output_dir=root,
        as_of=as_of or str(cfg.research.end),
        encoding=encoding,
    )
    write_market_index_discovery_report(market_index_discovery, root)
    stages.append(
        FirstMillionPipelineStage(
            "market_index_discovery",
            market_index_discovery.status,
            str(root / "market_index_discovery.json"),
            _market_index_discovery_message(market_index_discovery.to_dict()),
        )
    )
    market_context = (
        {
            "source": "market_regime",
            "payload": market_regime,
            "artifact": str(_market_regime_artifact(root)),
        }
        if market_regime
        else (
            {
                "source": "market_context_snapshot",
                "payload": market_context_snapshot,
                "artifact": str(root / "market_context_snapshot.json"),
            }
            if market_context_snapshot
            else {"source": "missing", "payload": {}, "artifact": str(root / "market_regime.json")}
        )
    )
    market_context_readiness = build_market_context_readiness_from_payload(market_context, as_of=as_of)
    write_market_context_readiness(market_context_readiness, root)
    stages.append(
        FirstMillionPipelineStage(
            "market_context_readiness",
            market_context_readiness.decision,
            str(root / "market_context_readiness.json"),
            _market_context_readiness_message(market_context_readiness.to_dict()),
        )
    )
    market_context_operator_packet = build_market_context_operator_packet(
        root,
        as_of=as_of,
        readiness=market_context_readiness,
    )
    write_market_context_operator_packet(market_context_operator_packet, root)
    stages.append(
        FirstMillionPipelineStage(
            "market_context_operator_packet",
            market_context_operator_packet.decision,
            str(root / "market_context_operator_packet.json"),
            _market_context_operator_packet_message(market_context_operator_packet.to_dict()),
        )
    )
    ohlcv_package = build_ohlcv_experiment_package_preflight(
        data_dir=data_root,
        report_dir=root,
        config_path=config_path,
        source_qa_answers=answers_path,
        source_qa_evidence_manifest=review_evidence_manifest_path,
        require_source_qa_evidence_manifest=require_source_qa_evidence_manifest,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
        as_of=as_of,
        encoding=encoding,
        csv_preview=csv_intake_preview,
        data_gap_plan=data_gap_plan,
        offline_package=offline_package,
        real_data_handoff=real_data_handoff,
        market_context_readiness=market_context_readiness,
    )
    write_ohlcv_experiment_package_preflight(ohlcv_package, root)
    stages.append(
        FirstMillionPipelineStage(
            "ohlcv_experiment_package",
            ohlcv_package.decision,
            str(root / "ohlcv_experiment_package.json"),
            _ohlcv_experiment_package_message(ohlcv_package.to_dict()),
        )
    )
    real_data_onboarding = build_real_data_batch_onboarding(
        data_dir=data_root,
        report_dir=root,
        config_path=config_path,
        raw_bars_csv=raw_bars_csv,
        source_qa_answers=answers_path,
        source_qa_evidence_manifest=evidence_manifest_path,
        require_source_qa_evidence_manifest=require_source_qa_evidence_manifest,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
        as_of=as_of,
        encoding=encoding,
        source_qa_packet=source_qa_operator_packet,
        ohlcv_package=ohlcv_package,
        raw_bars_discovery=raw_bars_discovery,
    )
    write_real_data_batch_onboarding(real_data_onboarding, root)
    stages.append(
        FirstMillionPipelineStage(
            "real_data_batch_onboarding",
            real_data_onboarding.decision,
            str(root / "real_data_batch_onboarding.json"),
            _real_data_batch_onboarding_message(real_data_onboarding.to_dict()),
        )
    )
    experiment_readiness = build_candidate_experiment_readiness(
        experiment_queue,
        stage_statuses={stage.name: stage.status for stage in stages},
        stage_messages={stage.name: stage.message for stage in stages},
        handoff_payload=real_data_handoff.to_dict(),
        source_metadata_summary=offline_package.source_metadata_summary,
        market_context=market_context,
        ohlcv_package_payload=ohlcv_package.to_dict(),
        as_of=as_of,
    )
    write_candidate_experiment_readiness(experiment_readiness, root)
    stages.append(
        FirstMillionPipelineStage(
            "candidate_experiment_readiness",
            experiment_readiness.decision,
            str(root / "candidate_experiment_readiness.json"),
            f"Runnable={experiment_readiness.runnable_count}, blocked={experiment_readiness.blocked_count}.",
        )
    )
    if not market_regime and market_context_snapshot:
        stages.append(
            FirstMillionPipelineStage(
                "market_context_snapshot",
                _snapshot_stage_status(market_context_snapshot),
                str(root / "market_context_snapshot.json"),
                _snapshot_message(market_context_snapshot),
            )
        )
    strategy_brief = build_first_million_strategy_brief(
        readiness=experiment_readiness,
        hypothesis_catalog=hypothesis_catalog,
        data_gap_plan=data_gap_plan.to_dict(),
        data_evidence_packet=data_evidence_packet.to_dict(),
        offline_package=offline_package.to_dict(),
        market_regime=market_regime,
        market_context_snapshot=market_context_snapshot,
        as_of=as_of,
    )
    write_first_million_strategy_brief(strategy_brief, root)
    stages.append(
        FirstMillionPipelineStage(
            "first_million_strategy_brief",
            "PASS" if strategy_brief.decision == "RUN_RESEARCH" else "WATCH",
            str(root / "first_million_strategy_brief.json"),
            f"Strategy brief decision={strategy_brief.decision}.",
        )
    )
    experiment_launch = build_candidate_experiment_launch(
        experiment_queue,
        experiment_readiness,
        report_dir=root,
        config_path=config_path,
        as_of=as_of,
    )
    write_candidate_experiment_launch(experiment_launch, root)
    stages.append(
        FirstMillionPipelineStage(
            "candidate_experiment_launch",
            experiment_launch.decision,
            str(root / "candidate_experiment_launch.json"),
            _launch_message(experiment_launch.to_dict()),
        )
    )
    experiment_run_packet = build_candidate_experiment_run_packet(
        experiment_launch,
        report_dir=root,
        config_path=config_path,
        as_of=as_of,
    )
    write_candidate_experiment_run_packet(experiment_run_packet, root)
    stages.append(
        FirstMillionPipelineStage(
            "candidate_experiment_run_packet",
            experiment_run_packet.decision,
            str(root / "candidate_experiment_run_packet.json"),
            _run_packet_message(experiment_run_packet.to_dict()),
        )
    )
    if experiment_launch.decision == "PASS":
        experiment_execution = run_candidate_experiment_execution(
            root,
            dry_run=not execute_candidate_experiment,
        )
    else:
        experiment_execution = CandidateExperimentExecutionReport(
            decision="BLOCK",
            launch_path=str(root / "candidate_experiment_launch.json"),
            report_dir=str(root),
            experiment_dir="",
            selected_candidate=str(experiment_launch.selected_candidate or ""),
            run_id=str(experiment_launch.run_id or ""),
            dry_run=not execute_candidate_experiment,
            steps=[],
            blockers=[
                f"Launch decision is {experiment_launch.decision}; execution requires PASS."
            ],
            next_actions=[
                "Fix launch or readiness blockers before running candidate experiment execution.",
                "Do not continue to completion review while execution is BLOCK.",
            ],
            prohibited_actions=CANDIDATE_EXECUTION_PROHIBITED_ACTIONS,
        )
    write_candidate_experiment_execution(experiment_execution, root)
    stages.append(
        FirstMillionPipelineStage(
            "candidate_experiment_execution",
            "WATCH" if experiment_execution.decision == "DRY_RUN" else experiment_execution.decision,
            str(root / "candidate_experiment_execution.json"),
            _execution_message(experiment_execution.to_dict()),
        )
    )
    experiment_completion = build_candidate_experiment_completion(root, as_of=as_of)
    write_candidate_experiment_completion(experiment_completion, root)
    stages.append(
        FirstMillionPipelineStage(
            "candidate_experiment_completion",
            experiment_completion.decision,
            str(root / "candidate_experiment_completion.json"),
            _completion_message(experiment_completion.to_dict()),
        )
    )

    goal_dir = root / "goal"
    goal_status = build_capital_goal_status(
        root,
        goal=goal,
        cfg=cfg,
        source_qa_dir=source_qa_dir,
        import_doctor_dir=intake_dir,
        offline_intake_dir=intake_dir,
        as_of=as_of,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
    )
    write_capital_goal_status(goal_status, goal_dir)
    stages.append(
        FirstMillionPipelineStage(
            "capital_goal_status",
            goal_status.decision,
            str(goal_dir / "capital_goal_status.json"),
            _capital_goal_status_message(goal_status.to_dict()),
        )
    )
    compounding_review = build_compounding_path_review(root, goal=goal)
    write_compounding_path_review(compounding_review, goal_dir)
    stages.append(
        FirstMillionPipelineStage(
            "compounding_path_review",
            compounding_review.decision,
            str(goal_dir / "compounding_path_review.json"),
            _compounding_message(compounding_review.to_dict()),
        )
    )
    strategy_brief = build_first_million_strategy_brief(
        readiness=experiment_readiness,
        hypothesis_catalog=hypothesis_catalog,
        data_gap_plan=data_gap_plan.to_dict(),
        data_evidence_packet=data_evidence_packet.to_dict(),
        offline_package=offline_package.to_dict(),
        market_regime=market_regime,
        market_context_snapshot=market_context_snapshot,
        capital_goal_status=goal_status.to_dict(),
        compounding_path_review=compounding_review.to_dict(),
        candidate_selection=_read_first_available_json(
            root / "candidate_selection.json",
            root / "weekly" / "candidate_selection.json",
        ),
        as_of=as_of,
    )
    write_first_million_strategy_brief(strategy_brief, root)

    readiness_card = build_first_million_readiness_card(
        root,
        as_of=as_of,
        cfg=cfg,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
    )
    write_first_million_readiness_card(readiness_card, root)
    stages.append(
        FirstMillionPipelineStage(
            "first_million_readiness",
            readiness_card.decision,
            str(root / "first_million_readiness.json"),
            _readiness_message(readiness_card.to_dict()),
        )
    )

    result = FirstMillionPipelineResult(
        decision=_decision(stages),
        output_dir=str(root),
        data_dir=str(data_root),
        config_path=str(config_path),
        goal=goal.to_dict(),
        stages=stages,
        next_actions=_next_actions(
            stages,
            intake.to_dict(),
            goal_status.to_dict(),
            data_evidence_packet.to_dict(),
        ),
        prohibited_actions=[
            "Do not claim a strategy can reach one million before real-data evidence passes.",
            "Do not treat research-only weekly output as a substitute for PASS source QA or guarded offline intake.",
            "Do not use demo/template/stale data as capital allocation evidence.",
            "Do not connect this pipeline to real broker order submission.",
            "Do not let LLM output override deterministic gates or human approval.",
        ],
    )
    write_first_million_pipeline_report(result, root)

    resolution_plan = build_first_million_resolution_plan(
        root,
        as_of=as_of,
        pipeline_payload=result.to_dict(),
    )
    write_first_million_resolution_plan(resolution_plan, root)
    daily_brief = build_first_million_daily_brief(
        root,
        as_of=as_of,
        pipeline_payload=result.to_dict(),
        resolution_payload=resolution_plan.to_dict(),
    )
    write_first_million_daily_brief(daily_brief, root)
    strategy_discovery_plan = build_strategy_discovery_plan(
        root,
        as_of=as_of,
        config_path=config_path,
    )
    write_strategy_discovery_plan(strategy_discovery_plan, root)
    stages.append(
        FirstMillionPipelineStage(
            "strategy_discovery_plan",
            strategy_discovery_plan.status,
            str(root / "strategy_discovery_plan.json"),
            _strategy_discovery_message(strategy_discovery_plan.to_dict()),
        )
    )
    evidence_ranking_dashboard = build_first_million_evidence_ranking_dashboard(
        root,
        data_dir=data_root,
        as_of=as_of,
    )
    write_first_million_evidence_ranking_dashboard(evidence_ranking_dashboard, root)
    stages.append(
        FirstMillionPipelineStage(
            "first_million_evidence_ranking_dashboard",
            evidence_ranking_dashboard.decision,
            str(root / "first_million_evidence_ranking_dashboard.json"),
            _evidence_ranking_dashboard_message(evidence_ranking_dashboard.to_dict()),
        )
    )
    result = FirstMillionPipelineResult(
        decision=_decision(stages),
        output_dir=str(root),
        data_dir=str(data_root),
        config_path=str(config_path),
        goal=goal.to_dict(),
        stages=stages,
        next_actions=_next_actions(
            stages,
            intake.to_dict(),
            goal_status.to_dict(),
            data_evidence_packet.to_dict(),
        ),
        prohibited_actions=[
            "Do not claim a strategy can reach one million before real-data evidence passes.",
            "Do not treat research-only weekly output as a substitute for PASS source QA or guarded offline intake.",
            "Do not use demo/template/stale data as capital allocation evidence.",
            "Do not connect this pipeline to real broker order submission.",
            "Do not let LLM output override deterministic gates or human approval.",
        ],
    )
    write_first_million_pipeline_report(result, root)
    resolution_plan = build_first_million_resolution_plan(
        root,
        as_of=as_of,
        pipeline_payload=result.to_dict(),
    )
    write_first_million_resolution_plan(resolution_plan, root)
    daily_brief = build_first_million_daily_brief(
        root,
        as_of=as_of,
        pipeline_payload=result.to_dict(),
        resolution_payload=resolution_plan.to_dict(),
    )
    write_first_million_daily_brief(daily_brief, root)
    return result


def write_first_million_pipeline_report(
    result: FirstMillionPipelineResult,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "first_million_pipeline.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "first_million_pipeline.md").write_text(result.to_markdown(), encoding="utf-8")
    return root


def write_source_qa_answers_provenance(
    provenance: SourceQAAnswersProvenance,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "source_qa_answers_provenance.json").write_text(
        json.dumps(provenance.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "source_qa_answers_provenance.md").write_text(
        provenance.to_markdown(),
        encoding="utf-8",
    )
    return root


def _source_answers_provenance(
    *,
    mode: str,
    answers_path: Path,
    input_path: Path,
    checklist_path: Path,
    generated_by: str,
    message: str,
) -> SourceQAAnswersProvenance:
    return SourceQAAnswersProvenance(
        mode=mode,
        answers_path=str(answers_path),
        input_path=str(input_path),
        input_sha256=_file_sha256(input_path),
        checklist_path=str(checklist_path),
        checklist_sha256=_file_sha256(checklist_path),
        generated_by=generated_by,
        message=message,
        prohibited_actions=[
            "Do not treat generated source QA answers as a data-quality PASS by themselves.",
            "Do not fabricate worksheet rows or CLI evidence fields to make preflight pass.",
            "Do not import offline data until source QA preflight and source review pass.",
            "Do not use this provenance record as a profit claim or live trading permission.",
            "Do not connect this workflow to real broker order submission.",
        ],
    )


def _write_source_answers_input_snapshot(
    output_dir: Path,
    *,
    mode: str,
    fields: dict[str, object],
) -> Path:
    path = output_dir / "source_qa_answers_input_snapshot.json"
    payload = {
        "mode": mode,
        "fields": {key: value for key, value in fields.items() if value is not None},
        "note": (
            "This snapshot records user-supplied source QA evidence fields for auditability. "
            "It is not a source QA PASS and cannot override deterministic gates."
        ),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _copy_provider_acquisition_ramp_report(
    source_path: str | Path | None,
    output_dir: Path,
) -> dict[str, Any]:
    if source_path is None:
        return {}
    payload = _read_json(Path(source_path))
    if not payload:
        payload = {
            "status": "WATCH",
            "provider": "unknown",
            "configured_stage_sizes": [],
            "executed_stage_count": 0,
            "stages": [],
            "research_only": True,
            "source_qa_provenance_status": "NOT_EVALUATED",
            "promotion_gate_effect": "NONE",
            "watch_items": [f"{source_path} is missing or unreadable."],
            "next_actions": [
                "Run provider acquisition ramp into an isolated cache, or continue with guarded offline CSV/TDX intake."
            ],
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "provider_acquisition_ramp.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "provider_acquisition_ramp.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if (source_md := Path(source_path).with_suffix(".md")).exists():
        (output_dir / "provider_acquisition_ramp.md").write_text(
            source_md.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    return payload


def _file_sha256(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return hashlib.sha256(data).hexdigest()


def _market_regime_artifact(root: Path) -> Path:
    local = root / "market_regime.json"
    return local if local.exists() else root / "weekly" / "market_regime.json"


def _review_message(payload: dict[str, Any]) -> str:
    findings = payload.get("findings", []) or []
    blocking = [finding for finding in findings if finding.get("severity") == "BLOCK"]
    if blocking:
        first = blocking[0]
        return f"{first.get('code')}: {first.get('message')}"
    watches = [finding for finding in findings if finding.get("severity") == "WATCH"]
    if watches:
        first = watches[0]
        return f"{first.get('code')}: {first.get('message')}"
    return "Source QA review passed."


def _source_preflight_message(payload: dict[str, Any]) -> str:
    items = payload.get("items", []) or []
    first_bad = _first_stage_item(items, {"BLOCK", "WATCH"})
    if first_bad:
        return f"{first_bad.get('field', 'source_qa')}: {first_bad.get('message', 'requires review')}"
    return "Source QA preflight has no unresolved source-stage gaps."


def _source_qa_evidence_readiness_message(payload: dict[str, Any]) -> str:
    sections = payload.get("sections", []) or []
    for section in sections:
        if isinstance(section, dict) and section.get("status") == "BLOCK":
            return f"{section.get('name')}: {section.get('summary', 'blocked')}"
    for section in sections:
        if isinstance(section, dict) and section.get("status") == "WATCH":
            return f"{section.get('name')}: {section.get('summary', 'watch')}"
    return "Source QA evidence readiness passed."


def _source_qa_closeout_message(payload: dict[str, Any]) -> str:
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    next_action = str(payload.get("next_action") or "").strip()
    if next_action:
        return (
            "worksheet_missing={worksheet}, attachment_missing={attachments}, "
            "open_actions={open_actions}; {next_action}"
        ).format(
            worksheet=int(counts.get("missing_worksheet_count") or 0),
            attachments=int(counts.get("missing_attachment_count") or 0),
            open_actions=int(counts.get("open_action_count") or 0),
            next_action=next_action,
        )
    return "Source QA closeout has no open actions; continue only through downstream deterministic gates."


def _worksheet_preflight_message(payload: dict[str, Any]) -> str:
    findings = payload.get("findings", []) or []
    first_bad = _first_stage_item(findings, {"BLOCK", "WATCH"})
    if first_bad:
        field = first_bad.get("field_or_question_id", "source_qa_worksheet")
        return f"{field}: {first_bad.get('message', 'worksheet requires review')}"
    return "Source QA worksheet preflight passed."


def _ohlcv_intake_closeout_message(payload: dict[str, Any]) -> str:
    blockers = payload.get("blockers", []) or []
    if blockers:
        return str(blockers[0])
    watches = payload.get("watch_items", []) or []
    if watches:
        return str(watches[0])
    return "source_qa={source}, raw={raw}, intake={intake}, latest={latest}".format(
        source=str(payload.get("source_qa_status") or "MISSING"),
        raw=str(payload.get("raw_discovery_status") or "MISSING"),
        intake=str(payload.get("offline_intake_status") or "MISSING"),
        latest=str(payload.get("latest_bar_date") or "missing"),
    )


def _intake_message(payload: dict[str, Any]) -> str:
    steps = payload.get("steps", []) or []
    for step in steps:
        if isinstance(step, dict) and step.get("status") == "BLOCK":
            return f"Stopped at {step.get('name')}: {step.get('message')}"
    for step in steps:
        if isinstance(step, dict) and step.get("status") == "WATCH":
            return f"WATCH at {step.get('name')}: {step.get('message')}"
    return "Offline intake passed."


def _promotion_metadata_message(payload: dict[str, Any]) -> str:
    blockers = payload.get("blockers", []) or []
    if blockers:
        return str(blockers[0])
    metadata = payload.get("metadata", {}) or {}
    metadata = metadata if isinstance(metadata, dict) else {}
    fingerprint = str(metadata.get("csv_dataset_fingerprint", "") or "")
    return f"Promotion metadata passed; csv_dataset_fingerprint={fingerprint[:12] or 'missing'}."


def _normalization_message(payload: dict[str, Any]) -> str:
    findings = payload.get("findings", []) or []
    blocks = [finding for finding in findings if finding.get("severity") == "BLOCK"]
    if blocks:
        first = blocks[0]
        return f"{first.get('code')}: {first.get('message')}"
    return (
        f"rows={payload.get('normalized_row_count', 0)}, "
        f"symbols={payload.get('symbol_count', 0)}, "
        f"raw_sha256={str(payload.get('raw_sha256') or '')[:12]}"
    )


def _manifest_message(payload: dict[str, Any]) -> str:
    version = payload.get("data_version", {}) or {}
    version = version if isinstance(version, dict) else {}
    csv_hash = str(version.get("csv_dataset_fingerprint", "") or "")
    raw_hash = str(version.get("raw_vendor_bars_sha256", "") or "")
    if raw_hash:
        return f"Run manifest recorded raw vendor hash {raw_hash[:12]} and CSV fingerprint {csv_hash[:12] or 'missing'}."
    return f"Run manifest recorded CSV fingerprint {csv_hash[:12] or 'missing'}."


def _gap_plan_message(payload: dict[str, Any]) -> str:
    items = payload.get("items", []) or []
    blockers = [item for item in items if isinstance(item, dict) and item.get("status") == "BLOCK"]
    if blockers:
        first = blockers[0]
        return f"{first.get('name')}: {first.get('message')}"
    watches = [item for item in items if isinstance(item, dict) and item.get("status") == "WATCH"]
    if watches:
        first = watches[0]
        return f"{first.get('name')}: {first.get('message')}"
    return "Data gap action plan has no BLOCK or WATCH items."


def _data_evidence_packet_message(payload: dict[str, Any]) -> str:
    blockers = payload.get("current_blockers", []) or []
    if blockers:
        first = blockers[0]
        return f"{first.get('name')}: {first.get('message')}"
    watches = payload.get("watch_items", []) or []
    if watches:
        first = watches[0]
        return f"{first.get('name')}: {first.get('message')}"
    commands = len(payload.get("immediate_commands", []) or [])
    return f"Data evidence action packet is ready; immediate_commands={commands}."


def _operator_handoff_status_message(payload: dict[str, Any]) -> str:
    open_count = int(payload.get("open_task_count", 0) or 0)
    p0_count = int(payload.get("p0_open_task_count", 0) or 0)
    source_count = int(payload.get("source_qa_open_task_count", 0) or 0)
    attachment_count = int(payload.get("source_qa_attachment_open_task_count", 0) or 0)
    export_count = int(payload.get("data_export_open_task_count", 0) or 0)
    if open_count:
        return (
            f"Operator handoff has {open_count} open tasks "
            f"(P0={p0_count}, source_qa={source_count}, "
            f"source_qa_attachment={attachment_count}, data_export={export_count})."
        )
    return "Operator handoff queue has no open tasks; deterministic gates still decide readiness."


def _csv_intake_preview_message(payload: dict[str, Any]) -> str:
    items = payload.get("items", []) or []
    blockers = [item for item in items if isinstance(item, dict) and item.get("status") == "BLOCK"]
    watches = [item for item in items if isinstance(item, dict) and item.get("status") == "WATCH"]
    if blockers:
        first = blockers[0]
        return f"{first.get('file_name')}: {first.get('message')}"
    if watches:
        first = watches[0]
        return f"{first.get('file_name')}: {first.get('message')}"
    bars = next((item for item in items if isinstance(item, dict) and item.get("role") == "bars"), {})
    return (
        "CSV columns mapped for import preview; "
        f"bars_rows={bars.get('normalized_rows', 0)}, symbols={bars.get('symbol_count', 0)}."
    )


def _tdx_discovery_message(payload: dict[str, Any]) -> str:
    best_root = str(payload.get("best_root") or "")
    roots = payload.get("roots", []) or []
    if best_root:
        return f"Best local TDX root: {best_root}."
    for item in roots:
        if isinstance(item, dict) and item.get("message"):
            return str(item.get("message"))
    return "No local TongDaXin .day roots were discovered."


def _raw_bars_discovery_message(payload: dict[str, Any]) -> str:
    best = str(payload.get("best_candidate") or "")
    candidates = payload.get("candidates", []) or []
    if best:
        return f"Best raw bars CSV candidate: {best}."
    for item in candidates:
        if isinstance(item, dict) and item.get("message"):
            return str(item.get("message"))
    return "No raw broker/vendor bars CSV candidates were discovered."


def _tdx_export_skipped_message(payload: dict[str, Any]) -> str:
    roots = payload.get("roots", []) or []
    for item in roots:
        if isinstance(item, dict) and item.get("message"):
            return f"TDX conversion skipped: {item.get('message')}"
    return "TDX conversion skipped because discovery is BLOCK."


def _tdx_export_message(payload: dict[str, Any]) -> str:
    if str(payload.get("status") or "").upper() == "BLOCK":
        failures = payload.get("failures", []) or []
        if failures:
            return str(failures[0])
        return "TDX conversion produced no usable bars."
    return (
        f"TDX bars converted: symbols={payload.get('symbol_count', 0)}, "
        f"rows={payload.get('row_count', 0)}."
    )


def _data_intake_router_message(payload: dict[str, Any]) -> str:
    route = str(payload.get("recommended_route") or "none")
    status = str(payload.get("status") or "UNKNOWN")
    routes = payload.get("routes", []) or []
    selected = next((item for item in routes if isinstance(item, dict) and item.get("name") == route), {})
    message = str(selected.get("message") or "Data intake route requires review.")
    return f"Recommended route={route}, status={status}: {message}"


def _offline_package_message(payload: dict[str, Any]) -> str:
    items = payload.get("items", []) or []
    blockers = [item for item in items if isinstance(item, dict) and item.get("status") == "BLOCK"]
    if blockers:
        first = blockers[0]
        return f"{first.get('name')}: {first.get('message')}"
    watches = [item for item in items if isinstance(item, dict) and item.get("status") == "WATCH"]
    if watches:
        first = watches[0]
        return f"{first.get('name')}: {first.get('message')}"
    provenance = format_source_provenance(_dict_payload(payload.get("source_metadata_summary")))
    if provenance:
        return f"Offline data package has no BLOCK or WATCH items; {provenance}."
    return "Offline data package has no BLOCK or WATCH items."


def _handoff_message(payload: dict[str, Any]) -> str:
    paths = payload.get("evidence_paths", []) or []
    blockers = [path for path in paths if isinstance(path, dict) and path.get("status") == "BLOCK"]
    if blockers:
        first = blockers[0]
        blocked_by = first.get("blocked_by", []) or []
        first_blocker = str(blocked_by[0]) if blocked_by else "Real-data handoff path is BLOCK."
        return f"{first.get('name')}: {first_blocker}"
    watches = [path for path in paths if isinstance(path, dict) and path.get("status") == "WATCH"]
    if watches:
        first = watches[0]
        return f"{first.get('name')}: {first.get('next_action')}"
    return "Real-data handoff checklist has no BLOCK or WATCH paths."


def _acquisition_message(payload: dict[str, Any]) -> str:
    latest = _dict_payload(payload.get("latest_import_attempt"))
    if latest.get("network_blocked"):
        message = str(latest.get("message") or "AKShare import was blocked by network/proxy access.")
        path = str(latest.get("path") or "")
        return f"{message} Latest import report={path or 'not supplied'}."
    blockers = payload.get("blockers", []) or []
    if blockers:
        return str(blockers[0])
    if str(payload.get("status", "")).upper() == "WATCH":
        return "Recent data acquisition plan has WATCH items."
    return "Recent data acquisition plan has no BLOCK items."


def _provider_smoke_stage_status(payload: dict[str, Any]) -> FirstMillionStatus:
    status = str(payload.get("status") or "WATCH").upper()
    # Provider smoke is route diagnostics only.  A failed provider smoke should
    # point the operator to offline CSV/TDX, not overrule those deterministic paths.
    return "PASS" if status == "PASS" else "WATCH"


def _provider_smoke_message(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "UNKNOWN")
    endpoint = str(payload.get("endpoint_viability") or "UNKNOWN")
    data_sufficiency = str(payload.get("data_sufficiency_status") or "UNKNOWN")
    imported = int(payload.get("imported_symbols") or 0)
    requested = int(payload.get("requested_symbols") or 0)
    if bool(payload.get("network_blocked")):
        route = str(payload.get("recommended_route") or "offline_csv_or_tdx")
        return f"Provider smoke={status}, endpoint={endpoint}; network/proxy blocked, route={route}."
    watch_items = payload.get("watch_items", []) or []
    if watch_items:
        return f"Provider smoke={status}, endpoint={endpoint}, data={data_sufficiency}: {watch_items[0]}"
    blockers = payload.get("blockers", []) or []
    if blockers:
        return f"Provider smoke={status}, endpoint={endpoint}: {blockers[0]}"
    return (
        f"Provider smoke={status}, endpoint={endpoint}, data={data_sufficiency}; "
        f"imported={imported}/{requested} symbols."
    )


def _provider_ramp_stage_status(payload: dict[str, Any]) -> FirstMillionStatus:
    status = str(payload.get("status") or "WATCH").upper()
    return "PASS" if status == "PASS" else "WATCH"


def _provider_ramp_message(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "UNKNOWN")
    provider = str(payload.get("provider") or "unknown")
    executed = int(payload.get("executed_stage_count") or len(payload.get("stages", []) or []))
    stages = [item for item in payload.get("stages", []) or [] if isinstance(item, dict)]
    last = stages[-1] if stages else {}
    imported = int(last.get("imported_symbols") or 0)
    requested = int(last.get("requested_symbols") or 0)
    if status.upper() == "BLOCK":
        return (
            f"Provider ramp={status} for {provider}; route diagnostics only, "
            f"last_stage_imported={imported}/{requested}. Continue offline CSV/TDX if needed."
        )
    if status.upper() == "WATCH":
        return (
            f"Provider ramp={status} for {provider}; executed_stages={executed}, "
            "WATCH is not PASS and cannot approve source QA."
        )
    return (
        f"Provider ramp={status} for {provider}; executed_stages={executed}, "
        f"last_stage_imported={imported}/{requested}. Acquisition evidence only."
    )


def _launch_message(payload: dict[str, Any]) -> str:
    blockers = payload.get("blocked_by", []) or []
    if blockers:
        return str(blockers[0])
    candidate = str(payload.get("selected_candidate") or "")
    run_id = str(payload.get("run_id") or "")
    return f"Launch plan ready for {candidate} ({run_id})."


def _run_packet_message(payload: dict[str, Any]) -> str:
    blockers = payload.get("blocked_by", []) or []
    if blockers:
        return str(blockers[0])
    candidate = str(payload.get("selected_candidate") or "")
    run_id = str(payload.get("run_id") or "")
    command_count = len(payload.get("command_bundle", []) or [])
    return f"Research-only run packet ready for {candidate} ({run_id}); commands={command_count}."


def _experiment_design_message(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "UNKNOWN")
    candidate_count = int(payload.get("candidate_count") or 0)
    scenario_count = int(payload.get("scenario_count") or 0)
    return (
        f"Pre-registered candidate stress design generated ({status}); "
        f"candidates={candidate_count}, scenarios={scenario_count}. "
        "Design only; no ranking, paper approval, or broker orders."
    )


def _completion_message(payload: dict[str, Any]) -> str:
    blockers = payload.get("blockers", []) or []
    if blockers:
        return str(blockers[0])
    watches = payload.get("watch_items", []) or []
    if watches:
        return str(watches[0])
    candidate = str(payload.get("selected_candidate") or "")
    run_id = str(payload.get("run_id") or "")
    return f"Experiment completion passed for {candidate} ({run_id})."


def _execution_message(payload: dict[str, Any]) -> str:
    blockers = payload.get("blockers", []) or []
    if blockers:
        return str(blockers[0])
    steps = payload.get("steps", []) or []
    decision = str(payload.get("decision") or "")
    return f"Execution {decision}; validated_steps={len(steps)}."


def _readiness_message(payload: dict[str, Any]) -> str:
    blockers = payload.get("blockers", []) or []
    if blockers:
        return str(blockers[0])
    watches = payload.get("watch_items", []) or []
    if watches:
        return str(watches[0])
    return "First-million readiness card has no BLOCK or WATCH gates."


def _strategy_discovery_message(payload: dict[str, Any]) -> str:
    decision = str(payload.get("decision") or "UNKNOWN")
    research_focus = payload.get("research_focus")
    focus = research_focus if isinstance(research_focus, dict) else {}
    focus_status = str(focus.get("status") or "UNKNOWN")
    blockers = [str(item) for item in payload.get("missing_evidence", []) or [] if item]
    if blockers:
        return f"Strategy discovery={decision}/{focus_status}: {blockers[0]}"
    allowed = [str(item) for item in payload.get("allowed_actions", []) or [] if item]
    if allowed:
        return f"Strategy discovery={decision}/{focus_status}; next={allowed[0]}"
    candidate = str(payload.get("top_candidate") or "none")
    runnable = int(payload.get("runnable_count") or 0)
    return f"Strategy discovery={decision}/{focus_status}; top_candidate={candidate}, runnable={runnable}."


def _evidence_ranking_dashboard_message(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    blocker = str(summary.get("first_ranking_blocker") or payload.get("next_action") or "none").rstrip(".")
    return (
        "Evidence ranking dashboard={decision}: next={next_area}; "
        "can_rank={can_rank}; top={top} ({basis}); first_blocker={blocker}."
    ).format(
        decision=str(payload.get("decision") or "MISSING"),
        next_area=str(payload.get("next_area") or "none"),
        can_rank=str(bool(payload.get("can_rank_candidates"))).lower(),
        top=str(payload.get("top_candidate") or "none"),
        basis=str(payload.get("top_candidate_basis") or "none"),
        blocker=blocker,
    )


def _manual_target_plan_message(payload: dict[str, Any]) -> str:
    candidate = str(payload.get("candidate") or "unknown")
    target_count = int(payload.get("target_count") or 0)
    warnings = payload.get("warnings", []) or []
    suffix = f" First warning: {warnings[0]}" if warnings else ""
    return (
        f"Manual target plan prepared for {candidate}; target_count={target_count}. "
        f"Manual reference only, not broker orders.{suffix}"
    )


def _micro_live_readiness_stage_status(payload: dict[str, Any]) -> FirstMillionStatus:
    decision = str(payload.get("decision") or "BLOCK").upper()
    if decision == "PASS":
        return "PASS"
    if decision == "WATCH":
        return "WATCH"
    return "BLOCK"


def _micro_live_readiness_message(payload: dict[str, Any]) -> str:
    if not payload:
        return "micro_live_readiness.json is missing; manual-only preparation did not complete."
    findings = payload.get("findings", []) or []
    for severity in ("BLOCK", "WATCH"):
        for finding in findings:
            if isinstance(finding, dict) and finding.get("severity") == severity:
                return (
                    f"{finding.get('code')}: {finding.get('message')} "
                    "This remains a manual-readiness review, not broker permission."
                )
    return "Micro-live readiness has no findings; manual approval and no-broker boundary still apply."


def _capital_goal_status_message(payload: dict[str, Any]) -> str:
    blockers = payload.get("blockers", []) or []
    if blockers:
        return str(blockers[0])
    watch_items = payload.get("watch_items", []) or []
    if watch_items:
        return str(watch_items[0])
    evidence = payload.get("evidence", []) or []
    blocked = [
        item
        for item in evidence
        if isinstance(item, dict) and str(item.get("status") or "").upper() == "BLOCK"
    ]
    if blocked:
        first = blocked[0]
        return f"{first.get('name', 'capital_goal_evidence')}: {first.get('message', 'BLOCK')}."
    return "Capital goal status has no BLOCK or WATCH evidence."


def _snapshot_message(payload: dict[str, Any]) -> str:
    label = str(payload.get("label") or "unknown")
    status = str(payload.get("status") or "UNKNOWN")
    if status.upper() == "BLOCK":
        findings = payload.get("findings", []) or []
        return str(findings[0]) if findings else "Market context snapshot is BLOCK."
    return (
        f"External market context snapshot is {label} ({status}); "
        "it is advisory context only and cannot replace market_regime.json."
    )


def _market_context_readiness_message(payload: dict[str, Any]) -> str:
    blockers = payload.get("blockers", []) or []
    if blockers:
        return str(blockers[0])
    watches = payload.get("watch_items", []) or []
    if watches:
        return str(watches[0])
    source = str(payload.get("source") or "unknown")
    label = str(payload.get("label") or "unknown")
    return f"Market context readiness passed via {source} ({label})."


def _market_index_discovery_message(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "UNKNOWN")
    best = str(payload.get("best_candidate") or "")
    if best:
        return f"Market index CSV discovery={status}: best_candidate={best}."
    candidates = payload.get("candidates", []) or []
    if candidates and isinstance(candidates[0], dict):
        findings = candidates[0].get("findings", []) or []
        if findings:
            return f"Market index CSV discovery={status}: {findings[0]}"
    return f"Market index CSV discovery={status}: no reviewed index CSV candidate found."


def _market_context_operator_packet_message(payload: dict[str, Any]) -> str:
    items = payload.get("items", []) or []
    missing_count = int(payload.get("missing_item_count") or len(items))
    source = str(payload.get("readiness_source") or "unknown")
    decision = str(payload.get("readiness_decision") or "UNKNOWN")
    if missing_count:
        first = items[0] if isinstance(items[0], dict) else {}
        return (
            f"Market context operator packet has {missing_count} open items; "
            f"first={first.get('item_type', 'item')}/{first.get('item_id', 'unknown')}."
        )
    return f"Market context operator packet has no open items; readiness={source}/{decision}."


def _source_qa_evidence_inbox_message(payload: dict[str, Any]) -> str:
    missing = int(payload.get("missing_item_count") or 0)
    invalid = int(payload.get("invalid_file_count") or 0)
    scanned = int(payload.get("scanned_file_count") or 0)
    if missing:
        return (
            f"Source QA evidence inbox is missing {missing} required attachments; "
            f"scanned_files={scanned}, invalid_files={invalid}."
        )
    if invalid:
        return f"Source QA evidence inbox has {invalid} invalid local files; scanned_files={scanned}."
    return f"Source QA evidence inbox mapped required attachments; scanned_files={scanned}."


def _evidence_intake_kit_message(payload: dict[str, Any]) -> str:
    files = int(payload.get("file_count") or 0)
    kit_dir = str(payload.get("kit_dir") or "")
    if files:
        return f"Evidence intake kit requests {files} real files; staging directory={kit_dir}."
    return "Evidence intake kit has no open file requests; rerun deterministic gates."


def _evidence_work_order_message(payload: dict[str, Any]) -> str:
    next_batch = str(payload.get("next_batch_id") or "none")
    open_count = int(payload.get("open_batch_count") or 0)
    return f"Evidence work order has {open_count} open batches; next={next_batch}."


def _data_intake_status_message(payload: dict[str, Any]) -> str:
    next_area = str(payload.get("next_area") or "none")
    next_action = str(payload.get("next_action") or "review data_intake_status.json")
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    raw_status = str(summary.get("raw_bars_status") or "UNKNOWN")
    source_status = str(summary.get("source_evidence_status") or "UNKNOWN")
    return (
        f"Data intake status next={next_area}; raw={raw_status}, "
        f"source_evidence={source_status}. {next_action}"
    )


def _ohlcv_experiment_package_message(payload: dict[str, Any]) -> str:
    blockers = payload.get("blockers", []) or []
    if blockers:
        return str(blockers[0])
    watches = payload.get("watch_items", []) or []
    if watches:
        return str(watches[0])
    bars = _dict_payload(payload.get("bars"))
    candidate = str(payload.get("candidate") or "price_volume_defensive")
    return (
        f"OHLCV package can launch guarded research for {candidate}; "
        f"symbols={bars.get('symbol_count', 0)}, rows={bars.get('normalized_rows', 0)}."
    )


def _real_data_batch_onboarding_message(payload: dict[str, Any]) -> str:
    blockers = payload.get("blockers", []) or []
    if blockers:
        return str(blockers[0])
    watches = payload.get("watch_items", []) or []
    if watches:
        return str(watches[0])
    steps = payload.get("steps", []) or []
    return f"Real-data batch onboarding has {len(steps)} checked steps and no required blockers."


def _snapshot_stage_status(payload: dict[str, Any]) -> FirstMillionStatus:
    status = str(payload.get("status") or "WATCH").upper()
    return "BLOCK" if status == "BLOCK" else "WATCH"


def _compounding_message(payload: dict[str, Any]) -> str:
    findings = payload.get("findings", []) or []
    for severity in ("BLOCK", "WATCH"):
        for finding in findings:
            if isinstance(finding, dict) and finding.get("severity") == severity:
                return f"{finding.get('code')}: {finding.get('message')}"
    projected = float(payload.get("projected_capital_at_horizon", 0.0) or 0.0)
    target = float(_dict_payload(payload.get("goal")).get("target_capital", 0.0) or 0.0)
    return f"Projected capital {projected:.2f} versus target {target:.2f}."


def _dict_payload(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_text_if_exists(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError:
        return None


def _read_first_available_json(*paths: Path) -> dict[str, Any]:
    for path in paths:
        payload = _read_json(path)
        if payload:
            return payload
    return {}


def _first_stage_item(items: list[Any], statuses: set[str]) -> dict[str, Any]:
    for item in items:
        if isinstance(item, dict) and str(item.get("status", "")).upper() in statuses:
            return item
    return {}


def _tdx_search_dirs(
    tdx_input_dir: str | Path | None,
    tdx_search_dirs: list[str | Path] | None,
) -> list[str | Path] | None:
    if tdx_input_dir is None:
        return tdx_search_dirs
    return [tdx_input_dir, *(tdx_search_dirs or [])]


def _decision(stages: list[FirstMillionPipelineStage]) -> Literal["PASS", "WATCH", "BLOCK"]:
    if any(stage.status == "BLOCK" for stage in stages):
        return "BLOCK"
    if any(stage.status in {"WATCH", "SKIPPED"} for stage in stages):
        return "WATCH"
    return "PASS"


def _next_actions(
    stages: list[FirstMillionPipelineStage],
    intake_payload: dict[str, Any],
    goal_payload: dict[str, Any],
    data_packet_payload: dict[str, Any] | None = None,
) -> list[str]:
    source_review = _stage(stages, "data_source_qa_review")
    if source_review and source_review.status == "BLOCK":
        packet = data_packet_payload or {}
        source_actions = [
            *_source_qa_worksheet_next_actions(packet),
            *_source_qa_attachment_next_actions(packet),
        ]
        if source_actions:
            return [
                *source_actions,
                (
                    "Replace template CSV rows with recent real A-share daily exports; use "
                    "results\\first_million\\operator_handoff.csv and "
                    "results\\first_million\\data_export_todo.csv for file-level actions."
                ),
            ]
        return [
            "Run write_data_source_qa_answers.py with real vendor/export evidence, then rerun first-million pipeline.",
            (
                "Replace template CSV rows with recent real A-share daily exports before "
                "expecting strategy research to run; use results\\first_million\\operator_handoff.csv."
            ),
        ]
    intake = _stage(stages, "offline_data_intake")
    if intake and intake.status == "BLOCK":
        return [str(item) for item in intake_payload.get("next_actions", [])]
    goal_next = [str(item) for item in goal_payload.get("next_actions", [])]
    if goal_next:
        return goal_next
    weekly = _stage(stages, "weekly_pipeline")
    if weekly and weekly.status == "SKIPPED":
        return ["Rerun after source QA and offline intake pass."]
    return ["Continue weekly evidence accumulation; do not increase capital without a fresh review."]


def _source_qa_attachment_next_actions(packet: dict[str, Any]) -> list[str]:
    manifest = packet.get("source_qa_evidence_manifest_status")
    if not isinstance(manifest, dict):
        return []
    status = str(manifest.get("status") or "UNKNOWN")
    if status == "PASS":
        return []
    missing_count = int(manifest.get("missing_attachment_count") or 0)
    invalid_count = int(manifest.get("invalid_attachment_count") or 0)
    next_command = str(manifest.get("next_command") or "").strip()
    if missing_count <= 0 and invalid_count <= 0:
        return []
    missing_ids = [
        str(item)
        for item in manifest.get("missing_attachment_ids", []) or []
        if str(item or "").strip()
    ][:6]
    invalid_items = [
        item
        for item in manifest.get("all_invalid_attachments", []) or manifest.get("invalid_attachments", []) or []
        if isinstance(item, dict)
    ]
    invalid_labels = [
        "{id}({state})".format(
            id=str(item.get("id") or item.get("path") or "unknown"),
            state=str(item.get("current_state") or "invalid"),
        )
        for item in invalid_items
        if str(item.get("id") or item.get("path") or "").strip()
    ][:6]
    suffix_parts: list[str] = []
    if missing_ids:
        suffix_parts.append(f"Missing: {', '.join(missing_ids)}")
    if invalid_labels:
        suffix_parts.append(f"Invalid: {', '.join(invalid_labels)}")
    suffix = f" {'; '.join(suffix_parts)}." if suffix_parts else ""
    actions = [
        (
            f"Prepare {missing_count} missing and {invalid_count} invalid source QA evidence "
            "attachments; use results\\first_million\\operator_handoff.csv and "
            "results\\first_million\\source_qa_attachment_todo.csv for local file targets. "
            "Use results\\first_million\\source_qa_evidence_attachment_plan.csv for suggested "
            f"file paths and weak-evidence warnings.{suffix}"
        )
    ]
    if next_command:
        actions.append(f"After adding source QA attachments, regenerate the manifest with: {next_command}")
    return actions


def _source_qa_worksheet_next_actions(packet: dict[str, Any]) -> list[str]:
    worksheet = packet.get("source_qa_worksheet_status")
    if not isinstance(worksheet, dict):
        return []
    status = str(worksheet.get("status") or "UNKNOWN")
    missing_count = int(worksheet.get("missing_row_count") or 0)
    next_command = str(worksheet.get("next_command") or "").strip()
    answers_command = str(worksheet.get("answers_command") or "").strip()
    path = str(worksheet.get("path") or "data_source_qa_evidence_worksheet.csv")
    if status == "ANSWERS_PRESENT":
        return []
    if missing_count > 0:
        missing_rows = worksheet.get("missing_rows", []) or []
        ids = [
            str(item.get("id"))
            for item in missing_rows
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        ][:6]
        suffix = f" First missing: {', '.join(ids)}." if ids else ""
        actions = [
            (
                f"Fill {missing_count} missing source QA worksheet rows in {path}; "
                "use results\\first_million\\operator_handoff.csv and "
                f"results\\first_million\\source_qa_worksheet_todo.csv for row numbers.{suffix}"
            ),
        ]
        if next_command:
            actions.append(f"After filling the worksheet, run worksheet preflight with: {next_command}")
        return actions
    if status in {"MISSING", "BLOCK"} and next_command:
        return [f"Create or refresh the source QA evidence worksheet with: {next_command}"]
    if status == "PASS" and next_command:
        actions = [f"Run worksheet preflight before generating answers with: {next_command}"]
        if answers_command:
            actions.append(f"If worksheet preflight passes, generate data_source_qa_answers.json with: {answers_command}")
        return actions
    return []


def _stage(
    stages: list[FirstMillionPipelineStage],
    name: str,
) -> FirstMillionPipelineStage | None:
    return next((stage for stage in stages if stage.name == name), None)
