"""Guarded workflow from local TongDaXin .day files to offline OHLCV evidence."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quantify.data.offline_intake import OfflineDataIntakeReport, run_offline_data_intake
from quantify.data.offline_package import (
    OfflineDataPackageReport,
    build_offline_data_package_report,
    write_offline_data_package_report,
)
from quantify.data.real_data_handoff import (
    RealDataHandoffChecklist,
    build_real_data_handoff_checklist,
    write_real_data_handoff_checklist,
)
from quantify.data.source_qa import build_data_source_qa, write_data_source_qa
from quantify.data.tdx_day import TdxDayExportReport, export_tdx_day_to_csv
from quantify.data.tdx_discovery import (
    TdxDayDiscoveryReport,
    build_tdx_day_discovery_report,
    write_tdx_day_discovery_report,
)
from quantify.utils.config import load_config

TdxIntakeStatus = Literal["PASS", "WATCH", "BLOCK", "SKIPPED"]


@dataclass(frozen=True, slots=True)
class TdxIntakeStep:
    name: str
    status: TdxIntakeStatus
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
class TdxOhlcvIntakeReport:
    status: Literal["PASS", "WATCH", "BLOCK"]
    input_dir: str
    data_dir: str
    output_dir: str
    config_path: str
    source_qa_answers_path: str
    source_qa_evidence_manifest_path: str
    require_source_qa_evidence_manifest: bool
    run_guarded_intake: bool
    steps: list[TdxIntakeStep]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "input_dir": self.input_dir,
            "data_dir": self.data_dir,
            "output_dir": self.output_dir,
            "config_path": self.config_path,
            "source_qa_answers_path": self.source_qa_answers_path,
            "source_qa_evidence_manifest_path": self.source_qa_evidence_manifest_path,
            "require_source_qa_evidence_manifest": self.require_source_qa_evidence_manifest,
            "run_guarded_intake": self.run_guarded_intake,
            "steps": [step.to_dict() for step in self.steps],
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# TDX OHLCV Intake: {self.status}",
            "",
            f"- Input directory: `{self.input_dir}`",
            f"- Data directory: `{self.data_dir}`",
            f"- Output directory: `{self.output_dir}`",
            f"- Config: `{self.config_path}`",
            f"- Source QA answers: `{self.source_qa_answers_path}`",
            f"- Source QA evidence manifest: `{self.source_qa_evidence_manifest_path}`",
            f"- Require evidence manifest: `{self.require_source_qa_evidence_manifest}`",
            f"- Run guarded intake: `{self.run_guarded_intake}`",
            "",
            "This workflow prepares OHLCV research evidence only. It is not a broker workflow, "
            "not a strategy recommendation, and not live trading permission.",
            "",
            "## Steps",
            "",
            "| step | status | artifact | message |",
            "| --- | --- | --- | --- |",
        ]
        for step in self.steps:
            lines.append(f"| `{step.name}` | `{step.status}` | `{step.artifact}` | {step.message} |")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def run_tdx_ohlcv_intake(
    *,
    input_dir: str | Path,
    data_dir: str | Path = "data_exports",
    output_dir: str | Path = "results/first_million",
    config_path: str | Path = "config/research_recent.yaml",
    source_qa_answers: str | Path | None = None,
    source_qa_evidence_manifest: str | Path | None = None,
    require_source_qa_evidence_manifest: bool = False,
    start: str | None = None,
    end: str | None = None,
    min_symbols: int = 300,
    min_trading_days: int = 240,
    as_of: str | None = None,
    encoding: str = "utf-8-sig",
    run_guarded_intake: bool = False,
) -> TdxOhlcvIntakeReport:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    data_root = Path(data_dir)
    cfg = load_config(config_path)
    resolved_start = start or str(cfg.research.start)
    resolved_end = end or str(cfg.research.end)
    answers_path = Path(source_qa_answers) if source_qa_answers else data_root / "data_source_qa_answers.json"
    manifest_path = (
        Path(source_qa_evidence_manifest)
        if source_qa_evidence_manifest
        else data_root / "source_qa_evidence_manifest.json"
    )
    steps: list[TdxIntakeStep] = []

    discovery = build_tdx_day_discovery_report(
        search_dirs=[input_dir],
        config_path=config_path,
        output_dir=root,
        data_output_dir=data_root,
        min_symbols=min_symbols,
        start=resolved_start,
        end=resolved_end,
    )
    write_tdx_day_discovery_report(discovery, root)
    steps.append(_discovery_step(discovery, root))
    if discovery.status == "BLOCK":
        return _final_report(
            input_dir=input_dir,
            data_dir=data_root,
            output_dir=root,
            config_path=config_path,
            answers_path=answers_path,
            manifest_path=manifest_path,
            require_source_qa_evidence_manifest=require_source_qa_evidence_manifest,
            run_guarded_intake=run_guarded_intake,
            steps=steps,
            next_actions=discovery.next_actions,
        )

    export = export_tdx_day_to_csv(
        input_dir=input_dir,
        output_dir=data_root,
        start=resolved_start,
        end=resolved_end,
    )
    steps.append(_export_step(export))
    if export.status == "BLOCK":
        return _final_report(
            input_dir=input_dir,
            data_dir=data_root,
            output_dir=root,
            config_path=config_path,
            answers_path=answers_path,
            manifest_path=manifest_path,
            require_source_qa_evidence_manifest=require_source_qa_evidence_manifest,
            run_guarded_intake=run_guarded_intake,
            steps=steps,
            next_actions=["Fix TDX conversion BLOCK before source QA or offline package checks."],
        )

    checklist = build_data_source_qa(
        config_path=config_path,
        output_dir=data_root,
        min_symbols=min_symbols,
        as_of=as_of,
    )
    write_data_source_qa(checklist, data_root)
    steps.append(
        TdxIntakeStep(
            "source_qa_checklist",
            "PASS",
            str(data_root / "data_source_qa.json"),
            "Source QA checklist and answers template were written.",
        )
    )

    handoff = build_real_data_handoff_checklist(
        data_dir=data_root,
        config_path=config_path,
        source_qa_answers=answers_path,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
        as_of=as_of,
        encoding=encoding,
    )
    write_real_data_handoff_checklist(handoff, root)
    steps.append(_handoff_step(handoff, root))

    package = build_offline_data_package_report(
        data_dir=data_root,
        config_path=config_path,
        source_qa_answers=answers_path,
        min_symbols=min_symbols,
        as_of=as_of,
        encoding=encoding,
    )
    write_offline_data_package_report(package, root)
    steps.append(_package_step(package, root))

    if run_guarded_intake:
        intake = run_offline_data_intake(
            data_dir=data_root,
            config_path=config_path,
            output_dir=root / "offline_intake",
            min_symbols=min_symbols,
            min_trading_days=min_trading_days,
            as_of=as_of,
            encoding=encoding,
            source_qa_checklist=data_root / "data_source_qa.json",
            source_qa_answers=answers_path,
            source_qa_evidence_manifest=manifest_path,
            require_source_qa_evidence_manifest=require_source_qa_evidence_manifest,
        )
        steps.append(_intake_step(intake, root))
    else:
        steps.append(
            TdxIntakeStep(
                "guarded_offline_intake",
                "SKIPPED",
                str(root / "offline_intake" / "offline_data_intake.json"),
                "Skipped because run_guarded_intake=false.",
            )
        )

    return _final_report(
        input_dir=input_dir,
        data_dir=data_root,
        output_dir=root,
        config_path=config_path,
        answers_path=answers_path,
        manifest_path=manifest_path,
        require_source_qa_evidence_manifest=require_source_qa_evidence_manifest,
        run_guarded_intake=run_guarded_intake,
        steps=steps,
        next_actions=_next_actions(steps, answers_path),
    )


def write_tdx_ohlcv_intake_report(
    report: TdxOhlcvIntakeReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "tdx_ohlcv_intake.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "tdx_ohlcv_intake.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _final_report(
    *,
    input_dir: str | Path,
    data_dir: Path,
    output_dir: Path,
    config_path: str | Path,
    answers_path: Path,
    manifest_path: Path,
    require_source_qa_evidence_manifest: bool,
    run_guarded_intake: bool,
    steps: list[TdxIntakeStep],
    next_actions: list[str],
) -> TdxOhlcvIntakeReport:
    report = TdxOhlcvIntakeReport(
        status=_combine([step.status for step in steps]),
        input_dir=str(input_dir),
        data_dir=str(data_dir),
        output_dir=str(output_dir),
        config_path=str(config_path),
        source_qa_answers_path=str(answers_path),
        source_qa_evidence_manifest_path=str(manifest_path),
        require_source_qa_evidence_manifest=require_source_qa_evidence_manifest,
        run_guarded_intake=run_guarded_intake,
        steps=steps,
        next_actions=next_actions,
        prohibited_actions=[
            "Do not treat TDX OHLCV intake as a license, adjustment, or PIT-fundamental review.",
            "Do not run strategy experiments while this report is BLOCK.",
            "Do not use this workflow for real broker order submission.",
            "Do not treat imported OHLCV data or any backtest as a promise of profit.",
        ],
    )
    write_tdx_ohlcv_intake_report(report, output_dir)
    return report


def _discovery_step(report: TdxDayDiscoveryReport, output_dir: Path) -> TdxIntakeStep:
    return TdxIntakeStep(
        "tdx_day_discovery",
        report.status,
        str(output_dir / "tdx_day_discovery.json"),
        f"best_root={report.best_root or 'none'}, status={report.status}",
    )


def _export_step(report: TdxDayExportReport) -> TdxIntakeStep:
    return TdxIntakeStep(
        "tdx_day_export",
        report.status,
        str(Path(report.output_dir) / "tdx_day_export.json"),
        f"symbols={report.symbol_count}, rows={report.row_count}",
    )


def _handoff_step(report: RealDataHandoffChecklist, output_dir: Path) -> TdxIntakeStep:
    return TdxIntakeStep(
        "real_data_handoff",
        report.status,
        str(output_dir / "real_data_handoff_checklist.json"),
        _first_bad_path_message(report.to_dict()) or "Real-data handoff has no BLOCK or WATCH paths.",
    )


def _package_step(report: OfflineDataPackageReport, output_dir: Path) -> TdxIntakeStep:
    return TdxIntakeStep(
        "offline_data_package",
        report.status,
        str(output_dir / "offline_data_package.json"),
        _first_bad_item_message(report.to_dict()) or "Offline data package has no BLOCK or WATCH items.",
    )


def _intake_step(report: OfflineDataIntakeReport, output_dir: Path) -> TdxIntakeStep:
    return TdxIntakeStep(
        "guarded_offline_intake",
        report.status,
        str(output_dir / "offline_intake" / "offline_data_intake.json"),
        _first_bad_step_message(report.to_dict()) or "Guarded offline intake completed.",
    )


def _first_bad_path_message(payload: dict[str, Any]) -> str:
    for path in payload.get("evidence_paths", []) or []:
        if isinstance(path, dict) and path.get("status") in {"BLOCK", "WATCH"}:
            blocked_by = path.get("blocked_by", []) or []
            detail = str(blocked_by[0]) if blocked_by else str(path.get("next_action", "requires review"))
            return f"{path.get('name')}: {detail}"
    return ""


def _first_bad_item_message(payload: dict[str, Any]) -> str:
    for item in payload.get("items", []) or []:
        if isinstance(item, dict) and item.get("status") in {"BLOCK", "WATCH"}:
            return f"{item.get('name')}: {item.get('message')}"
    return ""


def _first_bad_step_message(payload: dict[str, Any]) -> str:
    for item in payload.get("steps", []) or []:
        if isinstance(item, dict) and item.get("status") in {"BLOCK", "WATCH"}:
            return f"{item.get('name')}: {item.get('message')}"
    return ""


def _next_actions(steps: list[TdxIntakeStep], answers_path: Path) -> list[str]:
    status_by_name = {step.name: step.status for step in steps}
    if status_by_name.get("tdx_day_discovery") == "BLOCK":
        return ["Locate a valid TongDaXin vipdoc or lday directory and rerun the workflow."]
    if status_by_name.get("tdx_day_export") == "BLOCK":
        return ["Fix TDX conversion before source QA or offline package checks."]
    if status_by_name.get("real_data_handoff") == "BLOCK" or status_by_name.get("offline_data_package") == "BLOCK":
        return [
            (
                f"Fill {answers_path} with real TDX/vendor source evidence, preferably via "
                "examples\\write_tdx_source_qa_answers.py."
            ),
            "Rerun TDX OHLCV intake after source QA answers are present.",
        ]
    if status_by_name.get("guarded_offline_intake") == "SKIPPED":
        return [
            "Review package evidence, then rerun with --run-guarded-intake after source QA is filled.",
            "Keep the resulting data research-only until bootstrap, audit, and candidate gates pass.",
        ]
    if status_by_name.get("guarded_offline_intake") == "BLOCK":
        return ["Fix guarded offline intake BLOCK findings before candidate experiments."]
    return ["Rerun first-million pipeline and launch only READY research candidates."]


def _combine(statuses: list[TdxIntakeStatus]) -> Literal["PASS", "WATCH", "BLOCK"]:
    if any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    if any(status in {"WATCH", "SKIPPED"} for status in statuses):
        return "WATCH"
    return "PASS"
