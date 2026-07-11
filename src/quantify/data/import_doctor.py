"""Preflight doctor for offline research CSV imports."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from quantify.data.csv_contract import (
    CSVStatus,
    CSVValidationFinding,
    CSVValidationReport,
    RESEARCH_CSV_SCHEMAS,
    validate_research_csvs,
)


@dataclass(frozen=True, slots=True)
class DataImportDoctorCommand:
    name: str
    command: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "command": self.command, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class NetworkImportAttempt:
    path: str
    supplied: bool
    attempted: bool
    status: str
    start: str
    end: str
    imported_symbols: int
    failed_symbols: int
    bar_rows: int
    calendar_days: int
    network_blocked: bool
    message: str
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "supplied": self.supplied,
            "attempted": self.attempted,
            "status": self.status,
            "start": self.start,
            "end": self.end,
            "imported_symbols": self.imported_symbols,
            "failed_symbols": self.failed_symbols,
            "bar_rows": self.bar_rows,
            "calendar_days": self.calendar_days,
            "network_blocked": self.network_blocked,
            "message": self.message,
            "next_action": self.next_action,
        }


@dataclass(frozen=True, slots=True)
class DataImportDoctorReport:
    status: CSVStatus
    data_dir: str
    config_path: str
    cache_path: str
    start: str
    end: str
    min_symbols: int
    expected_files: dict[str, str]
    existing_files: list[str]
    missing_required_files: list[str]
    missing_recommended_files: list[str]
    export_requirements: dict[str, Any]
    validation: dict[str, Any] | None
    latest_import_attempt: NetworkImportAttempt | None = None
    findings: list[CSVValidationFinding] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    commands: list[DataImportDoctorCommand] = field(default_factory=list)
    prohibited_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "data_dir": self.data_dir,
            "config_path": self.config_path,
            "cache_path": self.cache_path,
            "start": self.start,
            "end": self.end,
            "min_symbols": self.min_symbols,
            "expected_files": self.expected_files,
            "existing_files": self.existing_files,
            "missing_required_files": self.missing_required_files,
            "missing_recommended_files": self.missing_recommended_files,
            "export_requirements": self.export_requirements,
            "validation": self.validation,
            "latest_import_attempt": self.latest_import_attempt.to_dict()
            if self.latest_import_attempt
            else None,
            "findings": [finding.to_dict() for finding in self.findings],
            "next_actions": self.next_actions,
            "commands": [command.to_dict() for command in self.commands],
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Data Import Doctor: {self.status}",
            "",
            f"- Data directory: `{self.data_dir}`",
            f"- Config: `{self.config_path or 'not supplied'}`",
            f"- Cache: `{self.cache_path}`",
            f"- Expected period: `{self.start or 'not specified'}` to `{self.end or 'not specified'}`",
            f"- Minimum symbols: {self.min_symbols}",
        ]
        if self.latest_import_attempt is not None:
            lines.extend(
                [
                    f"- Latest network import: `{self.latest_import_attempt.status}` "
                    f"({self.latest_import_attempt.message})",
                    f"- Network blocked: `{self.latest_import_attempt.network_blocked}`",
                ]
            )
        lines.extend(
            [
                "",
                "## Export Requirements",
                "",
                f"- Market: `{self.export_requirements['market']}`",
                f"- Bars date range: `{self.export_requirements['date_range']['start']}` to "
                f"`{self.export_requirements['date_range']['end']}`",
                f"- Minimum symbols: {self.export_requirements['minimum_universe']['min_symbols']}",
                f"- Universe mode: `{self.export_requirements['minimum_universe']['mode']}`",
                f"- Index code: `{self.export_requirements['minimum_universe']['index_code']}`",
                f"- Include ST: `{self.export_requirements['minimum_universe']['include_st']}`",
                f"- Minimum history days: {self.export_requirements['minimum_universe']['min_history_days']}",
                f"- Price adjustment: `{self.export_requirements['price_adjustment']}`",
                f"- Required files: `{', '.join(self.export_requirements['required_files'])}`",
                f"- Recommended files: `{', '.join(self.export_requirements['recommended_files'])}`",
                "",
                "## Files",
                "",
                "| role | path | status |",
                "| --- | --- | --- |",
            ]
        )
        existing = set(self.existing_files)
        missing_required = set(self.missing_required_files)
        for role, path in self.expected_files.items():
            if path in existing:
                status = "exists"
            elif path in missing_required:
                status = "missing required"
            else:
                status = "missing recommended"
            lines.append(f"| `{role}` | `{path}` | `{status}` |")
        lines.extend(["", "## Findings"])
        if self.findings:
            for finding in self.findings:
                lines.append(f"- `{finding.severity}` `{finding.code}`: {finding.message}")
        else:
            lines.append("- No findings.")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {action}" for action in self.next_actions)
        lines.extend(["", "## Commands"])
        for command in self.commands:
            lines.append(f"- {command.name}: {command.reason}")
            lines.append("")
            lines.append("```powershell")
            lines.append(command.command)
            lines.append("```")
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {action}" for action in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_data_import_doctor(
    *,
    data_dir: str | Path = "data_exports",
    config_path: str | Path | None = None,
    cache_path: str | Path | None = None,
    start: str | None = None,
    end: str | None = None,
    min_symbols: int = 300,
    encoding: str = "utf-8-sig",
    latest_import_report_path: str | Path | None = None,
) -> DataImportDoctorReport:
    """Inspect a CSV export directory and produce the next import commands."""
    config_values = _config_values(config_path)
    resolved_start = start or config_values.get("start", "")
    resolved_end = end or config_values.get("end", "")
    resolved_cache = str(cache_path or config_values.get("cache_path", "./data_cache/research_recent.db"))
    export_requirements = _export_requirements(
        config_values,
        start=resolved_start,
        end=resolved_end,
        min_symbols=min_symbols,
    )
    root = Path(data_dir)
    expected = {schema.role: str(root / schema.file_name) for schema in RESEARCH_CSV_SCHEMAS}
    missing_required = [
        expected[schema.role]
        for schema in RESEARCH_CSV_SCHEMAS
        if schema.required and not (root / schema.file_name).exists()
    ]
    missing_recommended = [
        expected[schema.role]
        for schema in RESEARCH_CSV_SCHEMAS
        if not schema.required and not (root / schema.file_name).exists()
    ]
    existing = [
        expected[schema.role]
        for schema in RESEARCH_CSV_SCHEMAS
        if (root / schema.file_name).exists()
    ]
    latest_import_attempt = _network_import_attempt(latest_import_report_path)
    findings: list[CSVValidationFinding] = []
    validation: CSVValidationReport | None = None
    if not root.exists():
        findings.append(
            CSVValidationFinding(
                "BLOCK",
                "DATA_EXPORT_DIR_MISSING",
                "CSV export directory does not exist; create templates or place vendor exports there.",
                {"data_dir": str(root)},
            )
        )
    elif missing_required:
        findings.append(
            CSVValidationFinding(
                "BLOCK",
                "REQUIRED_EXPORT_FILE_MISSING",
                "bars.csv is required before real A-share research can proceed.",
                {"missing_required_files": missing_required},
            )
        )
    else:
        validation = validate_research_csvs(
            bars_csv=root / "bars.csv",
            stock_info_csv=_existing_or_none(root / "stock_info.csv"),
            fundamentals_csv=_existing_or_none(root / "fundamentals.csv"),
            calendar_csv=_existing_or_none(root / "calendar.csv"),
            suspensions_csv=_existing_or_none(root / "suspensions.csv"),
            index_constituents_csv=_existing_or_none(root / "index_constituents.csv"),
            start=resolved_start or None,
            end=resolved_end or None,
            min_symbols=min_symbols,
            encoding=encoding,
        )
        findings.extend(validation.findings)
        findings.extend(_template_sample_findings(root))
    status = validation.status if validation else _combine_status(findings)
    status = _combine_status(findings) if findings else status
    commands = _commands(
        data_dir=root,
        config_path=str(config_path or ""),
        cache_path=resolved_cache,
        start=resolved_start,
        end=resolved_end,
        min_symbols=min_symbols,
        latest_import_attempt=latest_import_attempt,
    )
    return DataImportDoctorReport(
        status=status,
        data_dir=str(root),
        config_path=str(config_path or ""),
        cache_path=resolved_cache,
        start=resolved_start,
        end=resolved_end,
        min_symbols=min_symbols,
        expected_files=expected,
        existing_files=existing,
        missing_required_files=missing_required,
        missing_recommended_files=missing_recommended,
        export_requirements=export_requirements,
        validation=validation.to_dict() if validation else None,
        latest_import_attempt=latest_import_attempt,
        findings=findings,
        next_actions=_next_actions(
            status,
            missing_required,
            missing_recommended,
            findings,
            latest_import_attempt,
        ),
        commands=commands,
        prohibited_actions=[
            "Do not use sample template rows as real research evidence.",
            "Do not continue to bootstrap while this doctor report is BLOCK.",
            "Do not treat a CSV PASS as strategy approval; run bootstrap, data audit, robustness, and paper gates.",
            "Do not connect this workflow to a real broker or submit real orders.",
        ],
    )


def write_data_import_doctor_report(report: DataImportDoctorReport, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "data_import_doctor.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "data_import_doctor.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _config_values(config_path: str | Path | None) -> dict[str, str]:
    if config_path is None:
        return {}
    from quantify.utils.config import load_config

    cfg = load_config(config_path)
    data = cfg.to_dict()
    return {
        "start": str(data.get("research", {}).get("start", "")),
        "end": str(data.get("research", {}).get("end", "")),
        "cache_path": str(data.get("data", {}).get("cache_path", "")),
        "adjust": str(data.get("data", {}).get("adjust", "qfq")),
        "universe_mode": str(data.get("universe", {}).get("mode", "all_a")),
        "index_code": str(data.get("universe", {}).get("index_code", "")),
        "include_st": str(data.get("universe", {}).get("include_st", False)),
        "min_history_days": str(data.get("universe", {}).get("min_history_days", "")),
    }


def _export_requirements(
    config_values: dict[str, str],
    *,
    start: str,
    end: str,
    min_symbols: int,
) -> dict[str, Any]:
    required_files = [schema.file_name for schema in RESEARCH_CSV_SCHEMAS if schema.required]
    recommended_files = [schema.file_name for schema in RESEARCH_CSV_SCHEMAS if not schema.required]
    return {
        "market": "A-share daily equities",
        "date_range": {"start": start, "end": end},
        "minimum_universe": {
            "min_symbols": min_symbols,
            "mode": config_values.get("universe_mode", "all_a"),
            "index_code": config_values.get("index_code", ""),
            "include_st": _bool_text(config_values.get("include_st", "False")),
            "min_history_days": _int_text(config_values.get("min_history_days", "")),
        },
        "price_adjustment": config_values.get("adjust", "qfq") or "qfq",
        "required_files": required_files,
        "recommended_files": recommended_files,
        "bars_required_columns": next(schema.columns for schema in RESEARCH_CSV_SCHEMAS if schema.role == "bars"),
        "quality_floor": {
            "no_template_rows": True,
            "no_demo_data": True,
            "latest_bar_date_should_reach": end,
            "pass_doctor_before_import": True,
            "rerun_real_data_bootstrap_after_import": True,
        },
    }


def _existing_or_none(path: Path) -> Path | None:
    return path if path.exists() else None


def _commands(
    *,
    data_dir: Path,
    config_path: str,
    cache_path: str,
    start: str,
    end: str,
    min_symbols: int,
    latest_import_attempt: NetworkImportAttempt | None,
) -> list[DataImportDoctorCommand]:
    paths = {schema.role: data_dir / schema.file_name for schema in RESEARCH_CSV_SCHEMAS}
    period_args = _period_args(start, end)
    validate_command = (
        ".\\.venv\\Scripts\\python.exe examples\\validate_research_csv.py "
        f"--bars-csv {paths['bars']} "
        f"--stock-info-csv {paths['stock_info']} "
        f"--fundamentals-csv {paths['fundamentals']} "
        f"--calendar-csv {paths['calendar']} "
        f"--suspensions-csv {paths['suspensions']} "
        f"--index-constituents-csv {paths['index_constituents']} "
        f"{period_args}--min-symbols {min_symbols} "
        "--output-dir results\\import\\recent_csv_validation"
    )
    import_command = (
        ".\\.venv\\Scripts\\python.exe examples\\import_research_csv.py "
        f"--cache {cache_path} "
        f"--bars-csv {paths['bars']} "
        f"--stock-info-csv {paths['stock_info']} "
        f"--fundamentals-csv {paths['fundamentals']} "
        f"--calendar-csv {paths['calendar']} "
        f"--suspensions-csv {paths['suspensions']} "
        f"--index-constituents-csv {paths['index_constituents']} "
        f"--validate {period_args}--min-symbols {min_symbols} "
        "--output-dir results\\import\\recent_csv"
    )
    tdx_period_args = _period_args(start, end)
    bootstrap_config = config_path or "config\\research_recent.yaml"
    commands = [
        DataImportDoctorCommand(
            "write_templates",
            f".\\.venv\\Scripts\\python.exe examples\\write_data_export_templates.py --output-dir {data_dir}",
            "Create the expected CSV file names before replacing sample rows with vendor exports.",
        ),
        DataImportDoctorCommand(
            "normalize_vendor_bars",
            (
                ".\\.venv\\Scripts\\python.exe examples\\normalize_vendor_bars.py "
                "--input <raw-vendor-bars.csv> "
                f"--output-dir {data_dir} "
                f"{period_args}--min-symbols {min_symbols}"
            ),
            (
                "Normalize a raw broker/vendor daily bars CSV into bars.csv before validation; "
                "this is not source QA, cache import, strategy approval, or live trading permission."
            ),
        ),
        DataImportDoctorCommand(
            "discover_tdx_day",
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_tdx_day_discovery.py "
                f"--config {bootstrap_config} --output-dir results\\first_million "
                f"--data-output-dir {data_dir} --min-symbols {min_symbols}"
            ),
            "Find local TongDaXin vipdoc .day files for an offline OHLCV-only evidence path.",
        ),
        DataImportDoctorCommand(
            "run_tdx_ohlcv_intake",
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_tdx_ohlcv_intake.py "
                f"--input-dir <tdx-vipdoc-or-lday-dir> --data-dir {data_dir} "
                f"--output-dir results\\first_million --config {bootstrap_config} "
                f"--min-symbols {min_symbols} {tdx_period_args}".rstrip()
            ),
            "Convert local TDX .day files, write source QA templates, and run package checks.",
        ),
        DataImportDoctorCommand(
            "validate_csv",
            validate_command,
            "Validate local exports before writing the research cache.",
        ),
        DataImportDoctorCommand(
            "import_csv",
            import_command,
            "Write validated CSV data into the configured SQLite research cache.",
        ),
        DataImportDoctorCommand(
            "bootstrap_real_data",
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_real_data_bootstrap.py "
                f"--config {bootstrap_config} --output-dir results\\bootstrap_recent "
                f"--min-symbols {min_symbols}"
            ),
            "Re-check cache recency, breadth, sample split, and real-data eligibility after import.",
        ),
    ]
    if latest_import_attempt is not None and latest_import_attempt.network_blocked:
        return _prioritize_offline_commands(commands)
    return commands


def _period_args(start: str, end: str) -> str:
    args = []
    if start:
        args.extend(["--start", start])
    if end:
        args.extend(["--end", end])
    return " ".join(args) + (" " if args else "")


def _prioritize_offline_commands(
    commands: list[DataImportDoctorCommand],
) -> list[DataImportDoctorCommand]:
    order = {
        "discover_tdx_day": 0,
        "run_tdx_ohlcv_intake": 1,
        "write_templates": 2,
        "normalize_vendor_bars": 3,
        "validate_csv": 4,
        "import_csv": 5,
        "bootstrap_real_data": 6,
    }
    return sorted(commands, key=lambda item: order.get(item.name, len(order)))


def _next_actions(
    status: CSVStatus,
    missing_required: list[str],
    missing_recommended: list[str],
    findings: list[CSVValidationFinding],
    latest_import_attempt: NetworkImportAttempt | None,
) -> list[str]:
    finding_codes = {finding.code for finding in findings}
    network_blocked = latest_import_attempt is not None and latest_import_attempt.network_blocked
    stale_or_template = bool(
        missing_required
        or "TEMPLATE_EXPORT_UNREPLACED" in finding_codes
        or "BARS_END_BEFORE_EXPECTED" in finding_codes
    )
    if network_blocked and stale_or_template:
        return _blocked_offline_data_actions(finding_codes, missing_required=bool(missing_required))
    if network_blocked and status == "BLOCK":
        return [
            "Network import is unavailable, and local CSV validation still has BLOCK findings.",
            "Fix local CSV BLOCK findings, or switch to a fresh TDX/OHLCV-only or broker/vendor CSV export batch.",
            "Rerun the doctor before writing any data into the research cache.",
        ]
    if missing_required:
        return [
            "Create data_exports templates or place a real bars.csv export in the data directory.",
            "If you have a raw broker/vendor bars export, run examples\\normalize_vendor_bars.py into data_exports\\bars.csv first.",
            "Replace all sample rows with recent real A-share daily bars before validating.",
        ]
    if "TEMPLATE_EXPORT_UNREPLACED" in finding_codes:
        return [
            "Replace every template sample row with real broker or data-vendor A-share daily exports.",
            "Rerun the doctor before importing into the research cache.",
        ]
    if status == "BLOCK":
        return ["Fix BLOCK findings in data_import_doctor.md, then rerun the doctor."]
    if missing_recommended:
        actions = [
            "Consider adding recommended metadata CSVs for audit depth.",
            "If the missing evidence is acceptable for research, import with --validate and keep WATCH evidence.",
        ]
        if network_blocked:
            actions.insert(
                0,
                "Network import remains unavailable; continue only through guarded offline CSV intake for this batch.",
            )
        return actions
    if status == "WATCH":
        actions = [
            "Review WATCH findings, then import only if they are understood and acceptable for research.",
            "After import, run real_data_bootstrap and data_audit before strategy research.",
        ]
        if network_blocked:
            actions.insert(
                0,
                "Network import remains unavailable; keep the local broker/vendor or TDX export as the active evidence path.",
            )
        return actions
    actions = [
        "Import the validated CSV files into the configured research cache.",
        "Run real_data_bootstrap before any strategy research or paper workflow.",
    ]
    if network_blocked:
        actions.insert(
            0,
            "Network import remains unavailable; use the validated offline CSV batch instead of retrying provider data.",
        )
    return actions


def _blocked_offline_data_actions(
    finding_codes: set[str],
    *,
    missing_required: bool,
) -> list[str]:
    if missing_required:
        local_state = "missing bars.csv"
    elif "TEMPLATE_EXPORT_UNREPLACED" in finding_codes:
        local_state = "still template/sample data"
    elif "BARS_END_BEFORE_EXPECTED" in finding_codes:
        local_state = "stale before the configured research end date"
    else:
        local_state = "not usable"
    return [
        f"Network import is unavailable and local CSV evidence is {local_state}; do not import the current data_exports batch.",
        (
            "TDX/OHLCV-only path: locate TongDaXin vipdoc or lday .day files, run "
            "examples\\run_tdx_day_discovery.py, then examples\\run_tdx_ohlcv_intake.py; "
            "keep this path limited to OHLCV-only candidates until PIT fundamentals are supplied."
        ),
        (
            "Broker/vendor CSV path: export raw recent A-share daily OHLCV bars through the configured end date, "
            "run examples\\normalize_vendor_bars.py into data_exports\\bars.csv, add stock_info/calendar/suspensions "
            "when available, fill data_source_qa_answers.json, then run examples\\run_offline_data_intake.py."
        ),
    ]


def _network_import_attempt(path: str | Path | None) -> NetworkImportAttempt | None:
    if path is None:
        return None
    report_path = Path(path)
    payload = _read_json(report_path)
    if not payload:
        return NetworkImportAttempt(
            path=str(report_path),
            supplied=True,
            attempted=False,
            status="MISSING",
            start="",
            end="",
            imported_symbols=0,
            failed_symbols=0,
            bar_rows=0,
            calendar_days=0,
            network_blocked=False,
            message=f"{report_path.name} is missing or unreadable.",
            next_action="Run a small provider smoke import or use guarded offline CSV intake.",
        )
    status = str(payload.get("status") or "UNKNOWN").upper()
    reasons = _failure_reasons(payload.get("failures", []))
    network_blocked = _bool(payload.get("network_blocked")) or _network_blocked(reasons)
    imported = _int(payload.get("imported_symbols"))
    failed = _int(payload.get("failed_symbols"))
    bar_rows = _int(payload.get("bar_rows"))
    calendar_days = _int(payload.get("calendar_days"))
    if network_blocked:
        message = "Provider import was blocked by network/proxy access."
        next_action = (
            "Use TDX/OHLCV-only or broker/vendor offline CSV intake until provider access is fixed."
        )
    elif status == "PASS":
        message = f"Provider import reported PASS with {imported} symbols and {bar_rows} bars."
        next_action = "Run recent bootstrap against the imported cache."
    elif status == "WATCH":
        message = f"Provider import reported WATCH: imported={imported}, failed={failed}."
        next_action = "Inspect provider failures before treating the cache as evidence."
    else:
        detail = reasons[0] if reasons else "Provider import failed."
        message = f"Provider import reported {status}: {detail}"
        next_action = "Fix provider access or use guarded offline CSV intake."
    return NetworkImportAttempt(
        path=str(report_path),
        supplied=True,
        attempted=True,
        status=status,
        start=str(payload.get("start") or ""),
        end=str(payload.get("end") or ""),
        imported_symbols=imported,
        failed_symbols=failed,
        bar_rows=bar_rows,
        calendar_days=calendar_days,
        network_blocked=network_blocked,
        message=message,
        next_action=next_action,
    )


def _failure_reasons(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    reasons = []
    for item in value:
        if isinstance(item, dict):
            for key in ("reason", "error", "message"):
                reason = str(item.get(key) or "").strip()
                if reason:
                    reasons.append(reason)
                    break
        elif item:
            reasons.append(str(item))
    return reasons


def _network_blocked(reasons: list[str]) -> bool:
    markers = [
        "proxyerror",
        "unable to connect to proxy",
        "proxy/network block",
        "network block",
        "blocked by network",
        "network is unreachable",
        "remotedisconnected",
        "winerror 10013",
        "connection refused",
        "connection timed out",
        "timed out",
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


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _combine_status(findings: list[CSVValidationFinding]) -> CSVStatus:
    if any(finding.severity == "BLOCK" for finding in findings):
        return "BLOCK"
    if any(finding.severity == "WATCH" for finding in findings):
        return "WATCH"
    return "PASS"


def _template_sample_findings(root: Path) -> list[CSVValidationFinding]:
    template_files = []
    for schema in RESEARCH_CSV_SCHEMAS:
        path = root / schema.file_name
        if schema.role == "calendar" and _tdx_generated_calendar(root, path):
            continue
        if path.exists() and _matches_template_rows(path, schema.columns, schema.sample_rows):
            template_files.append(str(path))
    if not template_files:
        return []
    return [
        CSVValidationFinding(
            "BLOCK",
            "TEMPLATE_EXPORT_UNREPLACED",
            "One or more CSV files still contain the generated template sample rows.",
            {"template_files": template_files},
        )
    ]


def _tdx_generated_calendar(root: Path, path: Path) -> bool:
    report_path = root / "tdx_day_export.json"
    if not report_path.exists():
        return False
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if str(payload.get("status", "")).upper() == "BLOCK":
        return False
    calendar_csv = str(payload.get("calendar_csv") or "")
    return calendar_csv and Path(calendar_csv) == path


def _matches_template_rows(path: Path, columns: list[str], sample_rows: list[dict[str, Any]]) -> bool:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return False
    if list(rows[0]) != columns or len(rows) != len(sample_rows):
        return False
    expected = [{key: str(value) for key, value in row.items()} for row in sample_rows]
    return rows == expected


def _bool_text(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _int_text(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0
