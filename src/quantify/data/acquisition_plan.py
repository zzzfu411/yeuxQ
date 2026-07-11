"""Local acquisition plan for recent A-share research data."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from quantify.data.provider import DataProvider
from quantify.ops.bootstrap import build_real_data_bootstrap_report

AcquisitionStatus = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class AcquisitionStep:
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
class LatestImportAttempt:
    path: str
    attempted: bool
    status: str
    start: str
    end: str
    actual_bar_start: str
    actual_bar_end: str
    requested_symbols: int
    imported_symbols: int
    failed_symbols: int
    bar_rows: int
    calendar_days: int
    network_blocked: bool
    failure_stage: str
    recommended_route: str
    covers_requested_end: bool
    end_lag_days: int | None
    evidence_status: AcquisitionStatus
    message: str
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "attempted": self.attempted,
            "status": self.status,
            "start": self.start,
            "end": self.end,
            "actual_bar_start": self.actual_bar_start,
            "actual_bar_end": self.actual_bar_end,
            "requested_symbols": self.requested_symbols,
            "imported_symbols": self.imported_symbols,
            "failed_symbols": self.failed_symbols,
            "bar_rows": self.bar_rows,
            "calendar_days": self.calendar_days,
            "network_blocked": self.network_blocked,
            "failure_stage": self.failure_stage,
            "recommended_route": self.recommended_route,
            "covers_requested_end": self.covers_requested_end,
            "end_lag_days": self.end_lag_days,
            "evidence_status": self.evidence_status,
            "message": self.message,
            "next_action": self.next_action,
        }


@dataclass(frozen=True, slots=True)
class RecentDataAcquisitionPlan:
    status: AcquisitionStatus
    config_path: str
    cache_path: str
    start: str
    end: str
    min_symbols: int
    import_limit: int
    bootstrap_decision: str
    current_symbol_count: int
    current_latest_bar_date: str
    latest_import_attempt: LatestImportAttempt
    required_csv_files: list[dict[str, str]]
    steps: list[AcquisitionStep]
    blockers: list[str]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "config_path": self.config_path,
            "cache_path": self.cache_path,
            "start": self.start,
            "end": self.end,
            "min_symbols": self.min_symbols,
            "import_limit": self.import_limit,
            "bootstrap_decision": self.bootstrap_decision,
            "current_symbol_count": self.current_symbol_count,
            "current_latest_bar_date": self.current_latest_bar_date,
            "latest_import_attempt": self.latest_import_attempt.to_dict(),
            "required_csv_files": self.required_csv_files,
            "steps": [step.to_dict() for step in self.steps],
            "blockers": self.blockers,
            "notes": self.notes,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Recent A-share Data Acquisition Plan: {self.status}",
            "",
            f"- Config path: `{self.config_path}`",
            f"- Cache path: `{self.cache_path}`",
            f"- Period: `{self.start}` to `{self.end}`",
            f"- Min symbols: {self.min_symbols}",
            f"- Import limit: {self.import_limit}",
            f"- Current bootstrap decision: `{self.bootstrap_decision}`",
            f"- Current symbols: {self.current_symbol_count}",
            f"- Current latest bar date: `{self.current_latest_bar_date or 'missing'}`",
            f"- Latest import attempt: `{self.latest_import_attempt.status}` ({self.latest_import_attempt.message})",
            f"- Latest import period: `{self.latest_import_attempt.start or 'missing'}` to "
            f"`{self.latest_import_attempt.end or 'missing'}`",
            f"- Latest import actual bars: `{self.latest_import_attempt.actual_bar_start or 'missing'}` to "
            f"`{self.latest_import_attempt.actual_bar_end or 'missing'}`",
            f"- Latest import evidence: `{self.latest_import_attempt.evidence_status}`",
            "",
            "## Steps",
        ]
        lines.extend(f"- `{step.name}`: {step.purpose}\n  `{step.command}`" for step in self.steps)
        lines.extend(["", "## Required CSV Files", ""])
        lines.append("| file | required | columns |")
        lines.append("| --- | --- | --- |")
        for row in self.required_csv_files:
            lines.append(f"| `{row['file']}` | `{row['required']}` | `{row['columns']}` |")
        lines.extend(["", "## Blockers"])
        lines.extend(f"- {item}" for item in self.blockers) if self.blockers else lines.append("- None.")
        lines.extend(["", "## Notes"])
        lines.extend(f"- {item}" for item in self.notes)
        return "\n".join(lines) + "\n"


def build_recent_data_acquisition_plan(
    data: DataProvider,
    cfg,
    *,
    config_path: str | Path,
    as_of: str | None = None,
    min_symbols: int = 300,
    import_limit: int = 500,
    cache_exists_before_open: bool | None = None,
    cache_size_before_open: int | None = None,
    latest_import_report_path: str | Path | None = None,
) -> RecentDataAcquisitionPlan:
    bootstrap = build_real_data_bootstrap_report(
        data,
        cfg,
        config_path=config_path,
        cache_path=cfg.data.cache_path,
        as_of=as_of,
        min_symbols=min_symbols,
        cache_exists_before_open=cache_exists_before_open,
        cache_size_before_open=cache_size_before_open,
    )
    blockers = []
    if bool(getattr(cfg.research, "allow_demo_data", False)):
        blockers.append("Set research.allow_demo_data=false before treating results as recent real-market evidence.")
    if bootstrap.decision == "BLOCK":
        blockers.append("Current cache is not ready for recent A-share research evidence.")
    if bootstrap.symbol_count < min_symbols:
        blockers.append(f"Current cache has {bootstrap.symbol_count} symbols; target is at least {min_symbols}.")
    latest_import_attempt = _latest_import_attempt(
        latest_import_report_path,
        requested_end=str(cfg.research.end),
    )
    if latest_import_attempt.evidence_status == "BLOCK":
        blockers.append(latest_import_attempt.message)
    status: AcquisitionStatus = "PASS"
    if blockers:
        status = "BLOCK"
    elif bootstrap.decision == "WATCH" or latest_import_attempt.evidence_status == "WATCH":
        status = "WATCH"
    return RecentDataAcquisitionPlan(
        status=status,
        config_path=str(config_path),
        cache_path=str(cfg.data.cache_path),
        start=str(cfg.research.start),
        end=str(cfg.research.end),
        min_symbols=min_symbols,
        import_limit=import_limit,
        bootstrap_decision=bootstrap.decision,
        current_symbol_count=bootstrap.symbol_count,
        current_latest_bar_date=bootstrap.latest_bar_date,
        latest_import_attempt=latest_import_attempt,
        required_csv_files=bootstrap.required_files,
        steps=_steps(
            config_path,
            cfg.data.cache_path,
            import_limit,
            start=str(cfg.research.start),
            end=str(cfg.research.end),
            as_of=as_of,
            min_symbols=min_symbols,
            latest_import_report_path=latest_import_report_path,
        ),
        blockers=blockers,
        notes=[
            "This plan does not download data by itself.",
            "AKShare import may fail under restricted network conditions; failures must remain explicit BLOCK evidence.",
            "Offline CSV import must keep source QA answers, local evidence attachments, and guarded intake in one auditable chain.",
            "Do not run weekly pipeline for investment evidence until bootstrap is PASS on this recent config.",
        ],
    )


def write_recent_data_acquisition_plan(
    plan: RecentDataAcquisitionPlan,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "recent_data_acquisition_plan.json").write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "recent_data_acquisition_plan.md").write_text(plan.to_markdown(), encoding="utf-8")
    return root


def build_recent_data_acquisition_plan_from_config(
    *,
    config_path: str | Path,
    cache_path: str | Path | None = None,
    as_of: str | None = None,
    min_symbols: int = 300,
    import_limit: int = 500,
    latest_import_report_path: str | Path | None = None,
) -> RecentDataAcquisitionPlan:
    from quantify.data.storage import BarStorage
    from quantify.utils.config import load_config

    cfg = load_config(config_path)
    if cache_path is not None:
        payload = cfg.to_dict()
        data = dict(payload.get("data", {}))
        data["cache_path"] = str(cache_path)
        cfg = type(cfg)({**payload, "data": data})
    cache = Path(str(cfg.data.cache_path))
    exists_before_open = cache.exists()
    size_before_open = cache.stat().st_size if exists_before_open else 0
    provider = DataProvider(BarStorage(cache)) if exists_before_open else _EmptyDataProvider()
    return build_recent_data_acquisition_plan(
        provider,
        cfg,
        config_path=config_path,
        as_of=as_of,
        min_symbols=min_symbols,
        import_limit=import_limit,
        cache_exists_before_open=exists_before_open,
        cache_size_before_open=size_before_open,
        latest_import_report_path=latest_import_report_path,
    )


class _EmptyDataProvider:
    def all_symbols(self) -> list[str]:
        return []

    def trading_days(self, start: str, end: str) -> list[str]:
        return []

    def bars(self, symbols: list[str], start: str, end: str) -> pd.DataFrame:
        return pd.DataFrame()


def _steps(
    config_path: str | Path,
    cache_path: str | Path,
    import_limit: int,
    *,
    start: str,
    end: str,
    as_of: str | None,
    min_symbols: int,
    latest_import_report_path: str | Path | None,
) -> list[AcquisitionStep]:
    cfg_arg = str(config_path)
    cache_arg = str(cache_path)
    import_report_arg = (
        f" --latest-import-report {latest_import_report_path}" if latest_import_report_path else ""
    )
    as_of_arg = f" --as-of {as_of}" if as_of else ""
    return [
        AcquisitionStep(
            name="try_akshare_import",
            purpose="Import a broad recent A-share universe into an isolated recent cache.",
            command=(
                ".\\.venv\\Scripts\\python.exe examples/import_research_data.py "
                f"--config {cfg_arg} --limit {import_limit} --output-dir results\\import\\recent"
            ),
        ),
        AcquisitionStep(
            name="write_offline_csv_templates",
            purpose="Create schema-correct CSV templates for broker/vendor exports.",
            command=(
                ".\\.venv\\Scripts\\python.exe examples/write_data_export_templates.py "
                "--output-dir data_exports"
            ),
        ),
        AcquisitionStep(
            name="write_raw_bars_dropzone_kit",
            purpose=(
                "Create the retained raw daily-bars dropzone README and scan for broker/vendor CSV candidates "
                "without writing bars.csv."
            ),
            command=(
                ".\\.venv\\Scripts\\python.exe examples\\run_raw_bars_discovery.py "
                "--search-dir data_exports\\raw "
                f"--config {cfg_arg} --output-dir results\\first_million "
                "--data-output-dir data_exports --write-dropzone-kit "
                f"--min-symbols {min_symbols}"
            ),
        ),
        AcquisitionStep(
            name="write_source_qa_checklist",
            purpose="Create the source QA checklist, answer template, and fillable evidence worksheet.",
            command=(
                ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa.py "
                f"--config {cfg_arg} --output-dir data_exports --min-symbols {min_symbols}{as_of_arg}"
            ),
        ),
        AcquisitionStep(
            name="preflight_source_qa_worksheet",
            purpose="Check the filled source QA worksheet before converting it into answers.",
            command=(
                ".\\.venv\\Scripts\\python.exe examples\\run_data_source_qa_worksheet_preflight.py "
                "--checklist data_exports\\data_source_qa.json "
                "--worksheet data_exports\\data_source_qa_evidence_worksheet.csv "
                "--output-dir data_exports"
            ),
        ),
        AcquisitionStep(
            name="write_source_qa_evidence_manifest",
            purpose="Hash retained local evidence attachments for strict source QA review.",
            command=(
                ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
                "--checklist data_exports\\data_source_qa.json "
                "--evidence-dir data_exports\\source_qa_evidence --output-dir data_exports --strict"
            ),
        ),
        AcquisitionStep(
            name="write_source_qa_answers_from_worksheet",
            purpose="Convert a worksheet into answers only after strict attachment review is available.",
            command=(
                ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_answers.py "
                "--checklist data_exports\\data_source_qa.json "
                "--worksheet data_exports\\data_source_qa_evidence_worksheet.csv "
                "--output data_exports\\data_source_qa_answers.json "
                "--evidence-manifest data_exports\\source_qa_evidence_manifest.json "
                "--require-evidence-manifest"
            ),
        ),
        AcquisitionStep(
            name="review_source_qa_strict",
            purpose="Block offline intake unless source QA answers and required evidence attachments pass.",
            command=(
                ".\\.venv\\Scripts\\python.exe examples\\run_data_source_qa_review.py "
                "--checklist data_exports\\data_source_qa.json "
                "--answers data_exports\\data_source_qa_answers.json "
                "--evidence-manifest data_exports\\source_qa_evidence_manifest.json "
                "--require-evidence-manifest --output-dir results\\import\\source_qa"
            ),
        ),
        AcquisitionStep(
            name="review_source_qa_evidence_readiness",
            purpose="Summarize worksheet, answers, manifest, and strict source QA gates in one report.",
            command=(
                ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_evidence_readiness.py "
                "--checklist data_exports\\data_source_qa.json "
                "--worksheet data_exports\\data_source_qa_evidence_worksheet.csv "
                "--answers data_exports\\data_source_qa_answers.json "
                "--evidence-manifest data_exports\\source_qa_evidence_manifest.json "
                "--require-evidence-manifest --output-dir results\\import\\source_qa"
            ),
        ),
        AcquisitionStep(
            name="diagnose_offline_csv",
            purpose="Explain whether local CSV evidence is fresh enough, especially after provider/network failure.",
            command=(
                ".\\.venv\\Scripts\\python.exe examples/run_data_import_doctor.py "
                f"--data-dir data_exports --config {cfg_arg} --cache {cache_arg} "
                f"--min-symbols {min_symbols}{import_report_arg} --output-dir results\\import\\doctor"
            ),
        ),
        AcquisitionStep(
            name="convert_tdx_day_files",
            purpose="Convert local TongDaXin vipdoc .day files into bars.csv without using network APIs.",
            command=(
                ".\\.venv\\Scripts\\python.exe examples/convert_tdx_day.py "
                "--input-dir <tdx-vipdoc-or-lday-dir> --output-dir data_exports "
                f"--start {start} --end {end}"
            ),
        ),
        AcquisitionStep(
            name="validate_offline_csv",
            purpose="Validate exported CSV files before importing them into SQLite.",
            command=(
                ".\\.venv\\Scripts\\python.exe examples/validate_research_csv.py "
                "--bars-csv data_exports\\bars.csv "
                "--stock-info-csv data_exports\\stock_info.csv "
                "--fundamentals-csv data_exports\\fundamentals.csv "
                "--calendar-csv data_exports\\calendar.csv "
                "--suspensions-csv data_exports\\suspensions.csv "
                "--index-constituents-csv data_exports\\index_constituents.csv "
                f"--start {start} --end {end} --min-symbols {min_symbols} "
                "--output-dir results\\import\\recent_csv_validation"
            ),
        ),
        AcquisitionStep(
            name="guarded_offline_intake",
            purpose="Run guarded offline intake only after source QA, evidence manifest, doctor, validation, and bootstrap gates.",
            command=(
                ".\\.venv\\Scripts\\python.exe examples\\run_offline_data_intake.py "
                f"--data-dir data_exports --config {cfg_arg} --cache {cache_arg} "
                "--output-dir results\\import\\offline_intake "
                "--source-qa-answers data_exports\\data_source_qa_answers.json "
                "--source-qa-evidence-manifest data_exports\\source_qa_evidence_manifest.json "
                f"--require-source-qa-evidence-manifest --start {start} --end {end} "
                f"--min-symbols {min_symbols} --min-trading-days 240"
            ),
        ),
        AcquisitionStep(
            name="bootstrap_recent_cache",
            purpose="Verify recency, breadth, coverage, and sample split before research.",
            command=(
                ".\\.venv\\Scripts\\python.exe examples/run_real_data_bootstrap.py "
                f"--config {cfg_arg} --output-dir results\\bootstrap_recent --min-symbols {min_symbols}"
            ),
        ),
        AcquisitionStep(
            name="weekly_pipeline_recent",
            purpose="Run the full evidence chain only after recent bootstrap is PASS.",
            command=(
                ".\\.venv\\Scripts\\python.exe examples/run_weekly_pipeline.py "
                f"--config {cfg_arg} --starting-capital 100000 --target-capital 1000000 --years 8"
            ),
        ),
    ]


def _latest_import_attempt(path: str | Path | None, *, requested_end: str) -> LatestImportAttempt:
    if path is None:
        return LatestImportAttempt(
            path="",
            attempted=False,
            status="MISSING",
            start="",
            end="",
            actual_bar_start="",
            actual_bar_end="",
            requested_symbols=0,
            imported_symbols=0,
            failed_symbols=0,
            bar_rows=0,
            calendar_days=0,
            network_blocked=False,
            failure_stage="",
            recommended_route="offline_csv_or_tdx",
            covers_requested_end=False,
            end_lag_days=None,
            evidence_status="BLOCK",
            message="No AKShare import attempt report was supplied.",
            next_action=(
                "Run a small AKShare smoke import, or use offline CSV evidence: TDX/OHLCV-only intake for "
                "price-volume candidates, or broker/vendor CSV exports with source QA evidence."
            ),
        )
    report_path = Path(path)
    payload = _read_json(report_path)
    if not payload:
        return LatestImportAttempt(
            path=str(report_path),
            attempted=False,
            status="MISSING",
            start="",
            end="",
            actual_bar_start="",
            actual_bar_end="",
            requested_symbols=0,
            imported_symbols=0,
            failed_symbols=0,
            bar_rows=0,
            calendar_days=0,
            network_blocked=False,
            failure_stage="",
            recommended_route="offline_csv_or_tdx",
            covers_requested_end=False,
            end_lag_days=None,
            evidence_status="BLOCK",
            message=f"{report_path.name} is missing or unreadable.",
            next_action=(
                "Run a small AKShare smoke import, or use offline CSV evidence: TDX/OHLCV-only intake for "
                "price-volume candidates, or broker/vendor CSV exports with source QA evidence."
            ),
        )

    status = str(payload.get("status") or "UNKNOWN").upper()
    start = str(payload.get("start") or "")
    end = str(payload.get("end") or "")
    metadata = payload.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    requested = _int(payload.get("requested_symbols"))
    imported = _int(payload.get("imported_symbols"))
    failed = _int(payload.get("failed_symbols"))
    bar_rows = _int(payload.get("bar_rows"))
    calendar_days = _int(payload.get("calendar_days"))
    has_positive_bar_evidence = imported > 0 and bar_rows > 0 and calendar_days > 0
    actual_bar_start = _actual_coverage_value(
        metadata,
        "actual_bar_start",
        fallback=start,
        allow_fallback=has_positive_bar_evidence,
    )
    actual_bar_end = _actual_coverage_value(
        metadata,
        "actual_bar_end",
        fallback=end,
        allow_fallback=has_positive_bar_evidence,
    )
    reasons = _failure_reasons(payload.get("failures", []))
    network_blocked = _bool(payload.get("network_blocked")) or _network_blocked(reasons)
    failure_stage = str(payload.get("failure_stage") or metadata.get("failure_stage") or "").strip()
    recommended_route = str(payload.get("recommended_route") or metadata.get("recommended_route") or "").strip()
    end_lag_days = _end_lag_days(actual_bar_end, requested_end)
    covers_requested_end = end_lag_days is not None and end_lag_days <= 0
    evidence_status: AcquisitionStatus = "PASS"

    if status == "PASS":
        message = f"AKShare import succeeded for {imported}/{requested} symbols."
        next_action = "Run recent bootstrap on the imported cache, then rerun first-million pipeline."
    elif status == "WATCH":
        message = f"AKShare import partially succeeded: imported {imported}/{requested}, failed {failed}."
        next_action = "Inspect data_import.md failures before relying on the imported cache."
    elif network_blocked:
        message = "AKShare import was blocked by network/proxy access; no real market cache was created."
        next_action = (
            "Use offline CSV evidence: for TDX/OHLCV-only, run TDX discovery/intake and keep results limited "
            "to OHLCV-only candidates; for broker/vendor CSV, export recent bars.csv through the research "
            "end date, fill data_source_qa_answers.json, then run guarded offline intake."
        )
    else:
        detail = reasons[0] if reasons else "AKShare import failed."
        message = f"AKShare import failed: {detail}"
        next_action = (
            "Inspect data_import.md and either fix provider access, use TDX/OHLCV-only intake, "
            "or use broker/vendor CSV guarded offline intake."
        )
    if network_blocked:
        evidence_status = "BLOCK"
    elif not start or not end:
        evidence_status = "BLOCK"
        message = f"{message} Import report is missing start/end coverage evidence."
        next_action = "Regenerate data_import.json with start/end fields or use guarded offline CSV intake."
    elif not actual_bar_start or not actual_bar_end:
        evidence_status = "BLOCK"
        message = f"{message} Import report is missing actual_bar_start/actual_bar_end evidence."
        next_action = "Regenerate data_import.json with actual imported bar coverage metadata."
    elif end_lag_days is None:
        evidence_status = "BLOCK"
        message = f"{message} Import report actual bar end cannot be compared with requested research end."
        next_action = "Regenerate data_import.json with ISO date fields."
    elif end_lag_days > 0:
        evidence_status = "BLOCK"
        message = (
            f"{message} Import actual bars end at {actual_bar_end}, which is {end_lag_days} calendar days before "
            f"requested research end {requested_end}."
        )
        next_action = "Refresh/import data through the requested research end date before research."
    elif status == "BLOCK" or network_blocked or imported <= 0 or bar_rows <= 0 or calendar_days <= 0:
        evidence_status = "BLOCK"
    elif status == "WATCH" or failed > 0:
        evidence_status = "WATCH"

    return LatestImportAttempt(
        path=str(report_path),
        attempted=True,
        status=status,
        start=start,
        end=end,
        actual_bar_start=actual_bar_start,
        actual_bar_end=actual_bar_end,
        requested_symbols=requested,
        imported_symbols=imported,
        failed_symbols=failed,
        bar_rows=bar_rows,
        calendar_days=calendar_days,
        network_blocked=network_blocked,
        failure_stage=failure_stage,
        recommended_route=recommended_route,
        covers_requested_end=covers_requested_end,
        end_lag_days=end_lag_days,
        evidence_status=evidence_status,
        message=message,
        next_action=next_action,
    )


def _failure_reasons(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    reasons = []
    for item in value:
        if isinstance(item, dict):
            reason = str(item.get("reason") or "").strip()
            if reason:
                reasons.append(reason)
    return reasons


def _network_blocked(reasons: list[str]) -> bool:
    markers = [
        "proxyerror",
        "unable to connect to proxy",
        "remotedisconnected",
        "winerror 10013",
        "connection refused",
        "name resolution",
        "temporary failure in name resolution",
        "max retries exceeded",
    ]
    text = "\n".join(reasons).lower()
    return any(marker in text for marker in markers)


def _int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _end_lag_days(actual_end: str, requested_end: str) -> int | None:
    if not actual_end or not requested_end:
        return None
    try:
        return (pd.Timestamp(requested_end).date() - pd.Timestamp(actual_end).date()).days
    except (TypeError, ValueError):
        return None


def _actual_coverage_value(
    metadata: dict[str, Any],
    key: str,
    *,
    fallback: str,
    allow_fallback: bool,
) -> str:
    if key in metadata:
        return str(metadata.get(key) or "")
    return fallback if allow_fallback else ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
