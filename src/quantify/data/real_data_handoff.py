"""Operational handoff checklist for recent real A-share data."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from quantify.data.csv_contract import RESEARCH_CSV_SCHEMAS
from quantify.data.csv_intake_preview import build_csv_intake_preview
from quantify.data.gap_action_plan import DataGapActionPlan, build_data_gap_action_plan
from quantify.data.offline_package import OfflineDataPackageReport, build_offline_data_package_report
from quantify.utils.config import load_config

HandoffStatus = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class HandoffCommand:
    name: str
    command: str
    purpose: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "command": self.command,
            "purpose": self.purpose,
        }


@dataclass(frozen=True, slots=True)
class HandoffFileRequirement:
    role: str
    file_name: str
    path: str
    state: str
    columns: list[str]
    preview_status: str
    mapped_columns: list[str]
    missing_columns: list[str]
    preview_message: str
    required_for_ohlcv_minimum: bool
    required_for_pit_fundamental_candidates: bool
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "file_name": self.file_name,
            "path": self.path,
            "state": self.state,
            "columns": self.columns,
            "preview_status": self.preview_status,
            "mapped_columns": self.mapped_columns,
            "missing_columns": self.missing_columns,
            "preview_message": self.preview_message,
            "required_for_ohlcv_minimum": self.required_for_ohlcv_minimum,
            "required_for_pit_fundamental_candidates": self.required_for_pit_fundamental_candidates,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class HandoffEvidencePath:
    name: str
    status: HandoffStatus
    candidate_scope: list[str]
    required_files: list[str]
    recommended_files: list[str]
    required_evidence: list[str]
    blocked_by: list[str]
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "candidate_scope": self.candidate_scope,
            "required_files": self.required_files,
            "recommended_files": self.recommended_files,
            "required_evidence": self.required_evidence,
            "blocked_by": self.blocked_by,
            "next_action": self.next_action,
        }


@dataclass(frozen=True, slots=True)
class RealDataHandoffChecklist:
    status: HandoffStatus
    data_dir: str
    config_path: str
    cache_path: str
    start: str
    end: str
    as_of: str | None
    min_symbols: int
    min_trading_days: int
    source_qa_answers_path: str
    file_requirements: list[HandoffFileRequirement]
    evidence_paths: list[HandoffEvidencePath]
    current_blockers: list[str]
    next_actions: list[str]
    commands: list[HandoffCommand]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "data_dir": self.data_dir,
            "config_path": self.config_path,
            "cache_path": self.cache_path,
            "start": self.start,
            "end": self.end,
            "as_of": self.as_of,
            "min_symbols": self.min_symbols,
            "min_trading_days": self.min_trading_days,
            "source_qa_answers_path": self.source_qa_answers_path,
            "file_requirements": [item.to_dict() for item in self.file_requirements],
            "evidence_paths": [item.to_dict() for item in self.evidence_paths],
            "current_blockers": self.current_blockers,
            "next_actions": self.next_actions,
            "commands": [item.to_dict() for item in self.commands],
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Real Data Handoff Checklist: {self.status}",
            "",
            f"- Data directory: `{self.data_dir}`",
            f"- Config: `{self.config_path}`",
            f"- Cache target: `{self.cache_path}`",
            f"- Period: `{self.start}` to `{self.end}`",
            f"- As of: `{self.as_of or 'unspecified'}`",
            f"- Minimum symbols: {self.min_symbols}",
            f"- Minimum trading days: {self.min_trading_days}",
            f"- Source QA answers: `{self.source_qa_answers_path}`",
            "",
            "This checklist is an operational handoff for real-data evidence. It is not a "
            "strategy recommendation, profitability claim, or live trading permission.",
            "",
            "## Evidence Paths",
            "",
            "| path | status | candidate scope | required files | blocked by | next action |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for path in self.evidence_paths:
            scope = ", ".join(path.candidate_scope)
            required = ", ".join(path.required_files)
            blocked = "; ".join(path.blocked_by) if path.blocked_by else "none"
            lines.append(
                f"| `{path.name}` | `{path.status}` | `{scope}` | `{required}` | "
                f"{blocked} | {path.next_action} |"
            )
        lines.extend(
            [
                "",
                "## Files To Replace Or Supply",
                "",
                "| role | state | preview | missing columns | path | minimum OHLCV | PIT fundamental candidates | columns |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for item in self.file_requirements:
            missing = ", ".join(item.missing_columns) if item.missing_columns else "none"
            lines.append(
                f"| `{item.role}` | `{item.state}` | `{item.preview_status}` | `{missing}` | `{item.path}` | "
                f"`{item.required_for_ohlcv_minimum}` | "
                f"`{item.required_for_pit_fundamental_candidates}` | "
                f"`{', '.join(item.columns)}` |"
            )
        lines.extend(["", "## Current Blockers"])
        if self.current_blockers:
            lines.extend(f"- {item}" for item in self.current_blockers)
        else:
            lines.append("- None.")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Commands"])
        for command in self.commands:
            lines.append(f"- `{command.name}`: {command.purpose}")
            lines.append("")
            lines.append("```powershell")
            lines.append(command.command)
            lines.append("```")
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_real_data_handoff_checklist(
    *,
    data_dir: str | Path = "data_exports",
    config_path: str | Path = "config/research_recent.yaml",
    source_qa_answers: str | Path | None = None,
    source_qa_evidence_manifest: str | Path | None = None,
    require_source_qa_evidence_manifest: bool = False,
    min_symbols: int = 300,
    min_trading_days: int = 240,
    as_of: str | None = None,
    encoding: str = "utf-8-sig",
    data_gap_plan: DataGapActionPlan | None = None,
    offline_package: OfflineDataPackageReport | None = None,
) -> RealDataHandoffChecklist:
    """Build a single human handoff for closing real-data blockers."""
    data_root = Path(data_dir)
    cfg = load_config(config_path)
    answers_path = Path(source_qa_answers) if source_qa_answers else data_root / "data_source_qa_answers.json"
    gap = data_gap_plan or build_data_gap_action_plan(
        data_dir=data_root,
        config_path=config_path,
        source_qa_answers=answers_path,
        min_symbols=min_symbols,
        as_of=as_of,
        encoding=encoding,
    )
    package = offline_package or build_offline_data_package_report(
        data_dir=data_root,
        config_path=config_path,
        source_qa_answers=answers_path,
        source_qa_evidence_manifest=source_qa_evidence_manifest,
        require_source_qa_evidence_manifest=require_source_qa_evidence_manifest,
        min_symbols=min_symbols,
        as_of=as_of,
        encoding=encoding,
    )
    file_requirements = _file_requirements(data_root, gap, encoding=encoding)
    evidence_paths = _evidence_paths(gap, package, file_requirements)
    status = _status_from_paths(evidence_paths, gap, package)
    return RealDataHandoffChecklist(
        status=status,
        data_dir=str(data_root),
        config_path=str(config_path),
        cache_path=str(cfg.data.cache_path),
        start=str(cfg.research.start),
        end=str(cfg.research.end),
        as_of=as_of,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
        source_qa_answers_path=str(answers_path),
        file_requirements=file_requirements,
        evidence_paths=evidence_paths,
        current_blockers=_current_blockers(gap, package),
        next_actions=_next_actions(evidence_paths),
        commands=_commands(
            data_dir=data_root,
            config_path=config_path,
            cache_path=cfg.data.cache_path,
            start=str(cfg.research.start),
            end=str(cfg.research.end),
            min_symbols=min_symbols,
            min_trading_days=min_trading_days,
            answers_path=answers_path,
            as_of=as_of,
        ),
        prohibited_actions=[
            "Do not use generated CSV template rows as real A-share evidence.",
            "Do not run candidate experiments while the OHLCV minimum path is BLOCK.",
            "Do not compare fundamental-dependent candidates without PIT fundamental evidence.",
            "Do not treat this handoff PASS as profitability evidence.",
            "Do not connect this workflow to real broker order submission.",
            "Do not let LLM output override deterministic gates or human approval.",
        ],
    )


def write_real_data_handoff_checklist(
    checklist: RealDataHandoffChecklist,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "real_data_handoff_checklist.json").write_text(
        json.dumps(checklist.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "real_data_handoff_checklist.md").write_text(
        checklist.to_markdown(),
        encoding="utf-8",
    )
    return root


def _file_requirements(root: Path, gap: DataGapActionPlan, *, encoding: str) -> list[HandoffFileRequirement]:
    template_files = _template_files(gap)
    preview_by_role = _preview_by_role(root, encoding=encoding)
    return [
        _file_requirement(root, schema, template_files=template_files, preview_by_role=preview_by_role)
        for schema in RESEARCH_CSV_SCHEMAS
    ]


def _file_requirement(
    root: Path,
    schema,
    *,
    template_files: set[str],
    preview_by_role: dict[str, dict[str, Any]],
) -> HandoffFileRequirement:
    preview = preview_by_role.get(schema.role, {})
    return HandoffFileRequirement(
        role=schema.role,
        file_name=schema.file_name,
        path=str(root / schema.file_name),
        state=_file_state(root / schema.file_name, template_files),
        columns=schema.columns,
        preview_status=str(preview.get("status") or "MISSING"),
        mapped_columns=[str(value) for value in preview.get("mapped_columns", []) or []],
        missing_columns=[str(value) for value in preview.get("missing_columns", []) or []],
        preview_message=str(preview.get("message") or ""),
        required_for_ohlcv_minimum=schema.role == "bars",
        required_for_pit_fundamental_candidates=schema.role == "fundamentals",
        note=_file_note(schema.role),
    )


def _evidence_paths(
    gap: DataGapActionPlan,
    package: OfflineDataPackageReport,
    files: list[HandoffFileRequirement],
) -> list[HandoffEvidencePath]:
    ohlcv_blockers = _minimum_ohlcv_blockers(gap, files)
    ohlcv_watch = _minimum_ohlcv_watch_items(gap, package, files)
    ohlcv_status = "BLOCK" if ohlcv_blockers else "WATCH" if ohlcv_watch else "PASS"
    pit_blockers = _pit_blockers(gap, files)
    pit_watch = _pit_watch_items(files)
    pit_status = "BLOCK" if pit_blockers else "WATCH" if pit_watch else "PASS"
    return [
        HandoffEvidencePath(
            name="ohlcv_minimum_path",
            status=ohlcv_status,
            candidate_scope=[
                "price_volume_defensive",
                "low_turnover_price_volume",
                "low_turnover_low_concentration_price_volume",
                "trend_filtered_price_volume",
                "trend_filtered_quarterly_price_volume",
                "defensive_cash_guard_price_volume",
                "risk_off_cash_stop_price_volume",
                "regime_pause_price_volume",
            ],
            required_files=["bars.csv"],
            recommended_files=["stock_info.csv", "calendar.csv", "suspensions.csv"],
            required_evidence=[
                "Filled source QA answers with real vendor/export/license/adjustment evidence.",
                "Non-template recent A-share daily bars covering the configured research window.",
                "Import doctor has no BLOCK findings.",
            ],
            blocked_by=ohlcv_blockers,
            next_action=(
                "Run guarded offline intake, then launch only the OHLCV-only candidate."
                if ohlcv_status != "BLOCK"
                else "Supply real bars.csv and source QA evidence before any candidate experiment."
            ),
        ),
        HandoffEvidencePath(
            name="pit_fundamental_candidate_path",
            status=pit_status,
            candidate_scope=[
                "core_multifactor",
                "defensive_low_vol",
                "trend_filtered_core",
                "value_low_vol",
                "momentum_quality",
            ],
            required_files=["bars.csv", "fundamentals.csv"],
            recommended_files=["stock_info.csv", "calendar.csv", "suspensions.csv", "index_constituents.csv"],
            required_evidence=[
                "fundamentals.csv contains point-in-time pe_ttm and roe coverage.",
                "Source QA explicitly documents PIT provenance or keeps non-PIT data research-only.",
                "Candidate data-dependency review is PASS before comparing against OHLCV-only candidates.",
            ],
            blocked_by=pit_blockers,
            next_action=(
                "Run full candidate comparison only after PIT fundamentals are present and audited."
                if pit_status != "BLOCK"
                else "Keep fundamental-dependent candidates downgraded until PIT fundamentals are supplied."
            ),
        ),
    ]


def _minimum_ohlcv_blockers(
    gap: DataGapActionPlan,
    files: list[HandoffFileRequirement],
) -> list[str]:
    blockers = []
    item_status = {item.name: item.status for item in gap.items}
    item_message = {item.name: item.message for item in gap.items}
    required_items = [
        "data_dir",
        "source_qa_answers",
        "source_metadata",
        "source_qa_review",
        "csv_bars",
        "csv_template_rows",
        "import_doctor",
    ]
    for name in required_items:
        if item_status.get(name) == "BLOCK":
            blockers.append(f"{name}: {item_message.get(name, 'BLOCK')}")
    bars = _file(files, "bars")
    if bars and bars.state in {"missing", "template_sample_rows"}:
        blockers.append(f"bars.csv state is {bars.state}.")
    if bars and bars.preview_status == "BLOCK":
        blockers.append(_preview_blocker(bars))
    return _dedupe(blockers)


def _minimum_ohlcv_watch_items(
    gap: DataGapActionPlan,
    package: OfflineDataPackageReport,
    files: list[HandoffFileRequirement],
) -> list[str]:
    watches = []
    for item in gap.items:
        if item.status != "WATCH" or item.name not in {"source_qa_review", "import_doctor"}:
            continue
        if item.name == "import_doctor" and not _doctor_watch_relevant_to_ohlcv(item.message, files):
            continue
        watches.append(f"{item.name}: {item.message}")
    for item in package.items:
        if item.status != "WATCH" or item.name not in {"csv_inventory", "import_doctor"}:
            continue
        if item.name == "csv_inventory" and not _ohlcv_recommended_missing(files):
            continue
        if item.name == "import_doctor" and not _doctor_watch_relevant_to_ohlcv(item.message, files):
            continue
        watches.append(f"{item.name}: {item.message}")
    return _dedupe(watches)


def _pit_blockers(gap: DataGapActionPlan, files: list[HandoffFileRequirement]) -> list[str]:
    blockers = _minimum_ohlcv_blockers(gap, files)
    fundamentals = _file(files, "fundamentals")
    if fundamentals is None or fundamentals.state == "missing":
        blockers.append("fundamentals.csv is missing for valuation and quality candidates.")
    elif fundamentals.state == "template_sample_rows":
        blockers.append("fundamentals.csv still contains generated template rows.")
    if fundamentals and fundamentals.preview_status == "BLOCK":
        blockers.append(_preview_blocker(fundamentals))
    return _dedupe(blockers)


def _pit_watch_items(files: list[HandoffFileRequirement]) -> list[str]:
    watches = []
    for role in {"stock_info", "calendar", "suspensions", "index_constituents"}:
        item = _file(files, role)
        if item and item.state == "missing":
            watches.append(f"{item.file_name} is missing; PIT/execution audit depth is reduced.")
    return watches


def _ohlcv_recommended_missing(files: list[HandoffFileRequirement]) -> bool:
    return any(
        item.state == "missing"
        for item in files
        if item.role in {"stock_info", "calendar", "suspensions"}
    )


def _doctor_watch_relevant_to_ohlcv(
    message: str,
    files: list[HandoffFileRequirement],
) -> bool:
    """Return whether a doctor WATCH should demote the OHLCV-only path.

    Missing PIT fundamentals or index constituents should park PIT-dependent
    candidates, not the OHLCV-only candidate. Bars, calendar, stock-info,
    suspension, source, template, and generic doctor warnings still matter.
    """
    if _ohlcv_recommended_missing(files):
        return True
    normalized = message.upper()
    ohlcv_terms = {
        "BARS",
        "CALENDAR",
        "SUSPENSIONS",
        "STOCK_INFO",
        "SOURCE",
        "TEMPLATE",
        "DUPLICATE",
        "LIQUIDITY",
        "OHLC",
    }
    if any(term in normalized for term in ohlcv_terms):
        return True
    non_ohlcv_terms = {"FUNDAMENTALS", "INDEX_CONSTITUENTS"}
    if any(term in normalized for term in non_ohlcv_terms):
        return False
    return True


def _status_from_paths(
    paths: list[HandoffEvidencePath],
    gap: DataGapActionPlan,
    package: OfflineDataPackageReport,
) -> HandoffStatus:
    if any(path.name == "ohlcv_minimum_path" and path.status == "BLOCK" for path in paths):
        return "BLOCK"
    if gap.decision == "BLOCK" or package.status == "BLOCK":
        return "BLOCK"
    if any(path.status != "PASS" for path in paths):
        return "WATCH"
    if gap.decision == "WATCH" or package.status == "WATCH":
        return "WATCH"
    return "PASS"


def _current_blockers(
    gap: DataGapActionPlan,
    package: OfflineDataPackageReport,
) -> list[str]:
    blockers = [
        f"data_gap_action_plan.{item.name}: {item.message}"
        for item in gap.items
        if item.status == "BLOCK"
    ]
    blockers.extend(
        f"offline_data_package.{item.name}: {item.message}"
        for item in package.items
        if item.status == "BLOCK"
    )
    return _dedupe(blockers)


def _next_actions(paths: list[HandoffEvidencePath]) -> list[str]:
    ohlcv = next(path for path in paths if path.name == "ohlcv_minimum_path")
    pit = next(path for path in paths if path.name == "pit_fundamental_candidate_path")
    if ohlcv.status == "BLOCK":
        return [
            "Replace data_exports CSV templates with real recent A-share exports.",
            "Fill data_source_qa_answers.json with real vendor/export evidence.",
            "Rerun real data handoff and offline package checks before strategy research.",
        ]
    if pit.status == "BLOCK":
        return [
            "Proceed only with the OHLCV-only price_volume_defensive family after offline intake passes.",
            "Keep fundamental-dependent candidates BLOCK/WATCH until fundamentals.csv and PIT evidence are supplied.",
        ]
    if pit.status == "WATCH":
        return [
            "Review missing recommended audit files before full candidate comparison.",
            "Run guarded offline intake and keep WATCH evidence with the research report.",
        ]
    return [
        "Run guarded offline intake, then rerun first-million pipeline and candidate launch.",
        "Keep every generated artifact with the same data batch fingerprint.",
    ]


def _commands(
    *,
    data_dir: Path,
    config_path: str | Path,
    cache_path: str | Path,
    start: str,
    end: str,
    min_symbols: int,
    min_trading_days: int,
    answers_path: Path,
    as_of: str | None,
) -> list[HandoffCommand]:
    as_of_arg = f" --as-of {as_of}" if as_of else ""
    return [
        HandoffCommand(
            "write_export_request",
            (
                ".\\.venv\\Scripts\\python.exe examples\\write_data_export_request.py "
                f"--config {config_path} --output-dir {data_dir} --min-symbols {min_symbols}"
            ),
            "Generate the vendor/operator-facing CSV export contract.",
        ),
        HandoffCommand(
            "discover_tdx_day",
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_tdx_day_discovery.py "
                f"--config {config_path} --output-dir results\\first_million "
                f"--data-output-dir {data_dir} --min-symbols {min_symbols}"
            ),
            "Find local TongDaXin .day roots before converting OHLCV data.",
        ),
        HandoffCommand(
            "convert_tdx_day",
            (
                ".\\.venv\\Scripts\\python.exe examples\\convert_tdx_day.py "
                f"--input-dir <tdx-vipdoc-or-lday-dir> --output-dir {data_dir} "
                f"--start {start} --end {end}"
            ),
            "Optional local path for creating bars.csv from TongDaXin .day files.",
        ),
        HandoffCommand(
            "run_tdx_ohlcv_intake",
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_tdx_ohlcv_intake.py "
                f"--input-dir <tdx-vipdoc-or-lday-dir> --data-dir {data_dir} "
                f"--output-dir results\\first_million --config {config_path} "
                f"--min-symbols {min_symbols} --min-trading-days {min_trading_days}{as_of_arg}"
            ),
            "Run discovery, conversion, handoff, and package checks in one guarded local workflow.",
        ),
        HandoffCommand(
            "write_source_qa_checklist",
            (
                ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa.py "
                f"--config {config_path} --output-dir {data_dir} --min-symbols {min_symbols}{as_of_arg}"
            ),
            "Generate the source QA checklist and answer template before filling provenance.",
        ),
        HandoffCommand(
            "write_source_qa_evidence_worksheet",
            (
                ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_evidence_worksheet.py "
                f"--checklist {data_dir / 'data_source_qa.json'} --output-dir {data_dir}"
            ),
            "Create the fillable worksheet for ordinary vendor/broker CSV provenance.",
        ),
        HandoffCommand(
            "write_tdx_source_qa_answers",
            (
                ".\\.venv\\Scripts\\python.exe examples\\write_tdx_source_qa_answers.py "
                f"--checklist {data_dir / 'data_source_qa.json'} --output {answers_path} "
                f"--tdx-export-report {data_dir / 'tdx_day_export.json'} "
                "--input-dir <tdx-vipdoc-or-lday-dir> --operator <operator> "
                "--exported-at <local-time> --price-adjustment qfq "
                "--price-adjustment-evidence <real-tdx-adjustment-evidence> "
                "--license-evidence <real-license-evidence> "
                "--reviewed-by <name> --reviewed-at <date>"
            ),
            "Record TDX OHLCV-only provenance without pretending it proves PIT fundamentals.",
        ),
        HandoffCommand(
            "preflight_source_qa_worksheet",
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_data_source_qa_worksheet_preflight.py "
                f"--checklist {data_dir / 'data_source_qa.json'} "
                f"--worksheet {data_dir / 'data_source_qa_evidence_worksheet.csv'} --output-dir {data_dir}"
            ),
            "Check the filled worksheet before converting it into source QA answers.",
        ),
        HandoffCommand(
            "write_source_qa_evidence_manifest",
            (
                ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
                f"--checklist {data_dir / 'data_source_qa.json'} "
                f"--evidence-dir {data_dir / 'source_qa_evidence'} --output-dir {data_dir} --strict"
            ),
            "Hash retained local source evidence attachments before answers are committed.",
        ),
        HandoffCommand(
            "write_source_qa_answers_from_worksheet",
            (
                ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_answers.py "
                f"--checklist {data_dir / 'data_source_qa.json'} "
                f"--worksheet {data_dir / 'data_source_qa_evidence_worksheet.csv'} --output {answers_path} "
                f"--evidence-manifest {data_dir / 'source_qa_evidence_manifest.json'} "
                "--require-evidence-manifest"
            ),
            "Record source provenance from a worksheet only after strict attachment review.",
        ),
        HandoffCommand(
            "run_offline_package",
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_offline_data_package.py "
                f"--data-dir {data_dir} --config {config_path} --source-qa-answers {answers_path} "
                f"--min-symbols {min_symbols}{as_of_arg}"
            ),
            "Check the offline CSV package before writing the research cache.",
        ),
        HandoffCommand(
            "run_offline_intake",
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_offline_data_intake.py "
                f"--data-dir {data_dir} --config {config_path} --cache {cache_path} "
                f"--source-qa-answers {answers_path} --min-symbols {min_symbols} "
                f"--min-trading-days {min_trading_days}{as_of_arg}"
            ),
            "Run guarded local validation, import, and real-data bootstrap.",
        ),
        HandoffCommand(
            "rerun_first_million_pipeline",
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_first_million_pipeline.py "
                f"--config {config_path} --data-dir {data_dir} --output-dir results\\first_million "
                f"--source-qa-answers {answers_path} --min-symbols {min_symbols} "
                f"--min-trading-days {min_trading_days}{as_of_arg}"
            ),
            "Regenerate first-million readiness after the data package changes.",
        ),
        HandoffCommand(
            "launch_candidate_experiment",
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_candidate_experiment_launch.py "
                f"--report-dir results\\first_million --config {config_path}{as_of_arg}"
            ),
            "Launch the first eligible candidate only after deterministic gates pass.",
        ),
    ]


def _template_files(gap: DataGapActionPlan) -> set[str]:
    for item in gap.items:
        if item.name == "csv_template_rows" and item.status == "BLOCK":
            return {part.strip() for part in item.artifact.split(",") if part.strip()}
    return set()


def _file_state(path: Path, template_files: set[str]) -> str:
    if not path.exists():
        return "missing"
    if str(path) in template_files:
        return "template_sample_rows"
    return "present"


def _preview_by_role(root: Path, *, encoding: str) -> dict[str, dict[str, Any]]:
    preview = build_csv_intake_preview(data_dir=root, encoding=encoding)
    return {item.role: item.to_dict() for item in preview.items}


def _preview_blocker(item: HandoffFileRequirement) -> str:
    missing = ", ".join(item.missing_columns) if item.missing_columns else "unknown"
    message = item.preview_message or "CSV columns could not be mapped into the research schema."
    return f"{item.file_name} preview is BLOCK: {message} Missing columns={missing}."


def _file_note(role: str) -> str:
    notes = {
        "bars": "Minimum OHLCV path requires this file.",
        "stock_info": "Recommended for ST, delist, exchange, and industry audit.",
        "fundamentals": "Required before valuation or quality candidates are compared.",
        "calendar": "Recommended for missing-day and paper execution checks.",
        "suspensions": "Recommended for suspension and manual execution checks.",
        "index_constituents": "Recommended for point-in-time universe reproducibility.",
    }
    return notes.get(role, "Research data input.")


def _file(files: list[HandoffFileRequirement], role: str) -> HandoffFileRequirement | None:
    return next((item for item in files if item.role == role), None)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
