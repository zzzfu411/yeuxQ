"""CSV data contract for offline A-share research imports."""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from quantify.data.csv_research_importer import (
    _normalize_bars,
    _normalize_fundamentals,
    _normalize_stock_info,
    _normalize_suspensions,
    _read_calendar,
    _read_index_constituents,
)
from quantify.data.csv_research_importer import (
    _read_csv as _read_research_csv,
)

CSVStatus = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class CSVSchema:
    role: str
    file_name: str
    required: bool
    columns: list[str]
    description: str
    sample_rows: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "file_name": self.file_name,
            "required": self.required,
            "columns": self.columns,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class CSVValidationFinding:
    severity: CSVStatus
    code: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class CSVFileSummary:
    role: str
    path: str
    required: bool
    exists: bool
    size_bytes: int = 0
    sha256: str = ""
    modified_at_utc: str = ""
    columns: list[str] = field(default_factory=list)
    row_count: int = 0
    normalized_row_count: int = 0
    symbol_count: int = 0
    start: str = ""
    end: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "path": self.path,
            "required": self.required,
            "exists": self.exists,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "modified_at_utc": self.modified_at_utc,
            "columns": self.columns,
            "row_count": self.row_count,
            "normalized_row_count": self.normalized_row_count,
            "symbol_count": self.symbol_count,
            "start": self.start,
            "end": self.end,
        }


@dataclass(frozen=True, slots=True)
class CSVValidationReport:
    status: CSVStatus
    encoding: str
    dataset_fingerprint: str
    start: str
    end: str
    min_symbols: int
    schemas: list[CSVSchema]
    files: list[CSVFileSummary]
    metrics: dict[str, Any]
    findings: list[CSVValidationFinding]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "encoding": self.encoding,
            "dataset_fingerprint": self.dataset_fingerprint,
            "start": self.start,
            "end": self.end,
            "min_symbols": self.min_symbols,
            "schemas": [schema.to_dict() for schema in self.schemas],
            "files": [file.to_dict() for file in self.files],
            "metrics": self.metrics,
            "findings": [finding.to_dict() for finding in self.findings],
            "notes": self.notes,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Offline Research CSV Validation: {self.status}",
            "",
            f"- Encoding: `{self.encoding}`",
            f"- Dataset fingerprint: `{self.dataset_fingerprint or 'missing'}`",
            f"- Expected period: `{self.start or 'not specified'}` to `{self.end or 'not specified'}`",
            f"- Minimum symbols: {self.min_symbols}",
            "",
            "## File Summary",
            "",
            "| role | path | required | rows | normalized | symbols | period | sha256 |",
            "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
        for item in self.files:
            period = f"{item.start or '-'} to {item.end or '-'}"
            digest = item.sha256[:12] if item.sha256 else "-"
            lines.append(
                f"| `{item.role}` | `{item.path}` | `{item.required}` | "
                f"{item.row_count} | {item.normalized_row_count} | {item.symbol_count} | "
                f"`{period}` | `{digest}` |"
            )
        lines.extend(["", "## Findings"])
        if self.findings:
            for finding in self.findings:
                evidence = ", ".join(f"{key}={value}" for key, value in finding.evidence.items())
                lines.append(
                    f"- `{finding.severity}` `{finding.code}`: {finding.message}"
                    f" ({evidence or 'n/a'})"
                )
        else:
            lines.append("- No validation findings.")
        lines.extend(["", "## Required Schema", ""])
        lines.append("| file | required | columns |")
        lines.append("| --- | --- | --- |")
        for schema in self.schemas:
            required = "yes" if schema.required else "recommended"
            lines.append(f"| `{schema.file_name}` | `{required}` | `{','.join(schema.columns)}` |")
        lines.extend(["", "## Notes"])
        lines.extend(f"- {note}" for note in self.notes)
        return "\n".join(lines) + "\n"


RESEARCH_CSV_SCHEMAS: tuple[CSVSchema, ...] = (
    CSVSchema(
        role="bars",
        file_name="bars.csv",
        required=True,
        columns=["symbol", "date", "open", "high", "low", "close", "volume", "amount"],
        description="Daily OHLCV bars. One row per symbol and trading date.",
        sample_rows=[
            {
                "symbol": "600001",
                "date": "2024-01-02",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "volume": 1000000,
                "amount": 10200000,
            },
            {
                "symbol": "600001",
                "date": "2024-01-03",
                "open": 10.2,
                "high": 10.8,
                "low": 10.1,
                "close": 10.6,
                "volume": 1100000,
                "amount": 11660000,
            },
            {
                "symbol": "000001",
                "date": "2024-01-02",
                "open": 20.0,
                "high": 20.5,
                "low": 19.8,
                "close": 20.2,
                "volume": 2000000,
                "amount": 40400000,
            },
            {
                "symbol": "000001",
                "date": "2024-01-03",
                "open": 20.2,
                "high": 20.8,
                "low": 20.1,
                "close": 20.6,
                "volume": 2100000,
                "amount": 43260000,
            },
        ],
    ),
    CSVSchema(
        role="stock_info",
        file_name="stock_info.csv",
        required=False,
        columns=["symbol", "name", "exchange", "list_date", "delist_date", "industry", "is_st"],
        description="Static symbol metadata used for universe filtering and audit context.",
        sample_rows=[
            {
                "symbol": "600001",
                "name": "SampleSSE",
                "exchange": "SSE",
                "list_date": "2000-01-01",
                "delist_date": "",
                "industry": "sample",
                "is_st": 0,
            },
            {
                "symbol": "000001",
                "name": "SampleSZSE",
                "exchange": "SZSE",
                "list_date": "2000-01-01",
                "delist_date": "",
                "industry": "sample",
                "is_st": 0,
            },
        ],
    ),
    CSVSchema(
        role="fundamentals",
        file_name="fundamentals.csv",
        required=False,
        columns=["symbol", "date", "pe_ttm", "pb", "roe", "market_cap", "turnover_rate"],
        description="Point-in-time factor inputs for value, quality, size, and liquidity features.",
        sample_rows=[
            {
                "symbol": "600001",
                "date": "2024-01-02",
                "pe_ttm": 10.0,
                "pb": 1.2,
                "roe": 0.10,
                "market_cap": 10000000000,
                "turnover_rate": 0.02,
            },
            {
                "symbol": "000001",
                "date": "2024-01-02",
                "pe_ttm": 12.0,
                "pb": 1.4,
                "roe": 0.12,
                "market_cap": 12000000000,
                "turnover_rate": 0.03,
            },
        ],
    ),
    CSVSchema(
        role="calendar",
        file_name="calendar.csv",
        required=False,
        columns=["date", "is_open"],
        description="Trading calendar. Closed days should use is_open=0 or be omitted.",
        sample_rows=[
            {"date": "2024-01-02", "is_open": 1},
            {"date": "2024-01-03", "is_open": 1},
        ],
    ),
    CSVSchema(
        role="suspensions",
        file_name="suspensions.csv",
        required=False,
        columns=["symbol", "date", "is_suspended"],
        description="Suspension flags used by paper execution and manual-readiness gates.",
        sample_rows=[
            {"symbol": "600001", "date": "2024-01-03", "is_suspended": 0},
            {"symbol": "000001", "date": "2024-01-03", "is_suspended": 1},
        ],
    ),
    CSVSchema(
        role="index_constituents",
        file_name="index_constituents.csv",
        required=False,
        columns=["index_code", "date", "symbol"],
        description="Point-in-time index or research-universe membership snapshots.",
        sample_rows=[
            {"index_code": "000906", "date": "2024-01-02", "symbol": "600001"},
            {"index_code": "000906", "date": "2024-01-02", "symbol": "000001"},
        ],
    ),
)


def write_research_csv_templates(
    output_dir: str | Path,
    *,
    overwrite: bool = False,
) -> list[Path]:
    """Write example CSV files that match the offline research data contract."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for schema in RESEARCH_CSV_SCHEMAS:
        path = root / schema.file_name
        if path.exists() and not overwrite:
            raise FileExistsError(f"{path} already exists; pass overwrite=True to replace it")
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=schema.columns)
            writer.writeheader()
            writer.writerows(schema.sample_rows)
        written.append(path)
    (root / "README.md").write_text(_templates_readme(), encoding="utf-8")
    written.append(root / "README.md")
    return written


def validate_research_csvs(
    *,
    bars_csv: str | Path,
    stock_info_csv: str | Path | None = None,
    fundamentals_csv: str | Path | None = None,
    calendar_csv: str | Path | None = None,
    suspensions_csv: str | Path | None = None,
    index_constituents_csv: str | Path | None = None,
    start: str | None = None,
    end: str | None = None,
    min_symbols: int = 300,
    max_end_lag_days: int = 10,
    encoding: str = "utf-8-sig",
) -> CSVValidationReport:
    """Validate local CSV files before importing them into the research cache."""
    findings: list[CSVValidationFinding] = []
    files: list[CSVFileSummary] = []
    metrics: dict[str, Any] = {}
    bars: pd.DataFrame | None = None

    bars_path = Path(bars_csv)
    if not bars_path.exists():
        findings.append(
            CSVValidationFinding(
                "BLOCK",
                "BARS_CSV_MISSING",
                "bars.csv is required before offline research import.",
                {"path": str(bars_path)},
            )
        )
        files.append(_missing_file_summary("bars", bars_path, required=True))
    else:
        raw_bars = _read_csv(bars_path, encoding)
        files.append(_raw_summary("bars", bars_path, raw_bars, required=True))
        bars = _validate_bars(raw_bars, findings)
        if bars is not None:
            files[-1] = _frame_summary("bars", bars_path, raw_bars, bars, required=True)
            _validate_bar_scope(
                bars,
                findings,
                metrics,
                start=start,
                end=end,
                min_symbols=min_symbols,
                max_end_lag_days=max_end_lag_days,
            )

    stock_info = _validate_optional_table(
        role="stock_info",
        path=Path(stock_info_csv) if stock_info_csv else None,
        required=False,
        reader=lambda frame: _normalize_stock_info(frame),
        findings=findings,
        files=files,
        encoding=encoding,
    )
    fundamentals = _validate_optional_table(
        role="fundamentals",
        path=Path(fundamentals_csv) if fundamentals_csv else None,
        required=False,
        reader=lambda frame: _normalize_fundamentals(frame),
        findings=findings,
        files=files,
        encoding=encoding,
    )
    calendar = _validate_calendar(
        path=Path(calendar_csv) if calendar_csv else None,
        findings=findings,
        files=files,
        encoding=encoding,
    )
    suspensions = _validate_optional_table(
        role="suspensions",
        path=Path(suspensions_csv) if suspensions_csv else None,
        required=False,
        reader=lambda frame: _normalize_suspensions(frame),
        findings=findings,
        files=files,
        encoding=encoding,
    )
    index_constituents = _validate_index_constituents(
        path=Path(index_constituents_csv) if index_constituents_csv else None,
        findings=findings,
        files=files,
        encoding=encoding,
    )
    _cross_validate_tables(
        bars=bars,
        stock_info=stock_info,
        fundamentals=fundamentals,
        calendar=calendar,
        suspensions=suspensions,
        index_constituents=index_constituents,
        findings=findings,
        metrics=metrics,
    )
    return CSVValidationReport(
        status=_combine_status(findings),
        encoding=encoding,
        dataset_fingerprint=_dataset_fingerprint(files),
        start=start or "",
        end=end or "",
        min_symbols=min_symbols,
        schemas=list(RESEARCH_CSV_SCHEMAS),
        files=files,
        metrics=metrics,
        findings=findings,
        notes=[
            "Validation is local-only and does not connect to AKShare, broker APIs, or any live account.",
            "A PASS here only means the CSV files satisfy the import contract; bootstrap and data audit still decide readiness.",
            "Missing fundamentals, calendar, suspensions, or index constituents can be imported, but downstream gates may warn.",
        ],
    )


def write_csv_validation_report(report: CSVValidationReport, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "csv_validation.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "csv_validation.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _read_csv(path: Path, encoding: str) -> pd.DataFrame:
    try:
        return _read_research_csv(path, encoding)
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Could not read {path} with encoding={encoding}; try --encoding auto, gbk, or utf-8-sig"
        ) from exc


def _validate_bars(
    raw_bars: pd.DataFrame,
    findings: list[CSVValidationFinding],
) -> pd.DataFrame | None:
    amount_columns = {"amount", "成交额", "成交金额", "成交额(元)", "成交金额(元)"}
    if not any(str(column).strip() in amount_columns for column in raw_bars.columns):
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "BARS_AMOUNT_MISSING",
                "bars.csv has no amount column; importer will fill amount=0.",
            )
        )
    try:
        bars = _normalize_bars(raw_bars)
    except Exception as exc:  # noqa: BLE001 - report all user data problems.
        findings.append(
            CSVValidationFinding(
                "BLOCK",
                "BARS_CSV_INVALID",
                "bars.csv cannot be normalized into the research schema.",
                {"error": f"{type(exc).__name__}: {exc}"},
            )
        )
        return None
    dropped = len(raw_bars) - len(bars)
    if dropped:
        findings.append(
            CSVValidationFinding(
                "BLOCK",
                "BARS_ROWS_DROPPED",
                "Some bars have missing or non-numeric core OHLCV fields.",
                {"dropped_rows": dropped},
            )
        )
    if bars.empty:
        findings.append(
            CSVValidationFinding("BLOCK", "BARS_EMPTY", "bars.csv contains no usable bar rows.")
        )
        return bars
    duplicate_count = int(bars.duplicated(["symbol", "date"]).sum())
    if duplicate_count:
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "BARS_DUPLICATE_KEYS",
                "Duplicate symbol/date rows will be overwritten by SQLite upsert semantics.",
                {"duplicate_count": duplicate_count},
            )
        )
    invalid_ohlc = _invalid_ohlc_count(bars)
    if invalid_ohlc:
        findings.append(
            CSVValidationFinding(
                "BLOCK",
                "BARS_INVALID_OHLC",
                "Some rows have invalid OHLC relationships or non-positive prices.",
                {"invalid_ohlc_count": invalid_ohlc},
            )
        )
    non_positive_volume = int((pd.to_numeric(bars["volume"], errors="coerce") <= 0).sum())
    non_positive_amount = int((pd.to_numeric(bars["amount"], errors="coerce") <= 0).sum())
    if non_positive_volume or non_positive_amount:
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "BARS_NON_POSITIVE_LIQUIDITY",
                "Some rows have non-positive volume or amount.",
                {
                    "non_positive_volume_count": non_positive_volume,
                    "non_positive_amount_count": non_positive_amount,
                },
            )
        )
    return bars


def _validate_bar_scope(
    bars: pd.DataFrame,
    findings: list[CSVValidationFinding],
    metrics: dict[str, Any],
    *,
    start: str | None,
    end: str | None,
    min_symbols: int,
    max_end_lag_days: int,
) -> None:
    symbol_count = int(bars["symbol"].nunique())
    first_date = str(bars["date"].min()) if not bars.empty else ""
    last_date = str(bars["date"].max()) if not bars.empty else ""
    metrics.update(
        {
            "bars_symbol_count": symbol_count,
            "bars_start": first_date,
            "bars_end": last_date,
            "bars_row_count": len(bars),
        }
    )
    if symbol_count < min_symbols:
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "SYMBOL_COUNT_BELOW_TARGET",
                "The CSV universe is below the configured recent-research target.",
                {"symbol_count": symbol_count, "min_symbols": min_symbols},
            )
        )
    if start and first_date and first_date > start:
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "BARS_START_AFTER_EXPECTED",
                "bars.csv starts after the requested research start date.",
                {"bars_start": first_date, "expected_start": start},
            )
        )
    if end and last_date and last_date < end:
        lag_days = _calendar_day_lag(last_date, end)
        if lag_days is not None:
            metrics["bars_end_lag_days"] = lag_days
        findings.append(
            CSVValidationFinding(
                "BLOCK" if lag_days is not None and lag_days > max_end_lag_days else "WATCH",
                "BARS_END_BEFORE_EXPECTED",
                "bars.csv ends before the requested research end date.",
                {
                    "bars_end": last_date,
                    "expected_end": end,
                    "lag_days": lag_days,
                    "max_end_lag_days": max_end_lag_days,
                },
            )
        )


def _validate_optional_table(
    *,
    role: str,
    path: Path | None,
    required: bool,
    reader,
    findings: list[CSVValidationFinding],
    files: list[CSVFileSummary],
    encoding: str,
) -> pd.DataFrame | None:
    if path is None:
        findings.append(
            CSVValidationFinding(
                "WATCH",
                f"{role.upper()}_CSV_MISSING",
                f"{role}.csv is recommended for real-data audit depth.",
            )
        )
        files.append(_missing_file_summary(role, Path(""), required=required))
        return None
    if not path.exists():
        findings.append(
            CSVValidationFinding(
                "WATCH",
                f"{role.upper()}_CSV_MISSING",
                f"{role}.csv was requested but does not exist.",
                {"path": str(path)},
            )
        )
        files.append(_missing_file_summary(role, path, required=required))
        return None
    raw = _read_csv(path, encoding)
    try:
        normalized = reader(raw)
    except Exception as exc:  # noqa: BLE001 - report all user data problems.
        findings.append(
            CSVValidationFinding(
                "WATCH" if not required else "BLOCK",
                f"{role.upper()}_CSV_INVALID",
                f"{role}.csv cannot be normalized into the research schema.",
                {"error": f"{type(exc).__name__}: {exc}"},
            )
        )
        files.append(_raw_summary(role, path, raw, required=required))
        return None
    files.append(_frame_summary(role, path, raw, normalized, required=required))
    duplicate_count = int(normalized.duplicated(["symbol"]).sum()) if "symbol" in normalized else 0
    if duplicate_count and role == "stock_info":
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "STOCK_INFO_DUPLICATE_SYMBOLS",
                "Duplicate stock_info symbols will be overwritten by SQLite upsert semantics.",
                {"duplicate_count": duplicate_count},
            )
        )
    duplicate_keys = (
        int(normalized.duplicated(["symbol", "date"]).sum())
        if {"symbol", "date"}.issubset(normalized.columns)
        else 0
    )
    if duplicate_keys:
        findings.append(
            CSVValidationFinding(
                "WATCH",
                f"{role.upper()}_DUPLICATE_KEYS",
                f"Duplicate {role} symbol/date rows will be overwritten by SQLite upsert semantics.",
                {"duplicate_count": duplicate_keys},
            )
        )
    return normalized


def _validate_calendar(
    *,
    path: Path | None,
    findings: list[CSVValidationFinding],
    files: list[CSVFileSummary],
    encoding: str,
) -> list[str] | None:
    if path is None:
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "CALENDAR_CSV_MISSING",
                "calendar.csv is recommended; importer will infer calendar from bar dates.",
            )
        )
        files.append(_missing_file_summary("calendar", Path(""), required=False))
        return None
    if not path.exists():
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "CALENDAR_CSV_MISSING",
                "calendar.csv was requested but does not exist.",
                {"path": str(path)},
            )
        )
        files.append(_missing_file_summary("calendar", path, required=False))
        return None
    raw = _read_csv(path, encoding)
    try:
        dates = _read_calendar(raw)
    except Exception as exc:  # noqa: BLE001
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "CALENDAR_CSV_INVALID",
                "calendar.csv cannot be normalized into open trading dates.",
                {"error": f"{type(exc).__name__}: {exc}"},
            )
        )
        files.append(_raw_summary("calendar", path, raw, required=False))
        return None
    normalized = pd.DataFrame({"date": dates})
    files.append(_frame_summary("calendar", path, raw, normalized, required=False))
    if not dates:
        findings.append(
            CSVValidationFinding("BLOCK", "CALENDAR_EMPTY", "calendar.csv has no open trading days.")
        )
    return dates


def _validate_index_constituents(
    *,
    path: Path | None,
    findings: list[CSVValidationFinding],
    files: list[CSVFileSummary],
    encoding: str,
) -> pd.DataFrame | None:
    if path is None:
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "INDEX_CONSTITUENTS_CSV_MISSING",
                "index_constituents.csv is recommended for point-in-time universe reproducibility.",
            )
        )
        files.append(_missing_file_summary("index_constituents", Path(""), required=False))
        return None
    if not path.exists():
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "INDEX_CONSTITUENTS_CSV_MISSING",
                "index_constituents.csv was requested but does not exist.",
                {"path": str(path)},
            )
        )
        files.append(_missing_file_summary("index_constituents", path, required=False))
        return None
    raw = _read_csv(path, encoding)
    try:
        rows = _read_index_constituents(raw, default_index_code="000906")
    except Exception as exc:  # noqa: BLE001
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "INDEX_CONSTITUENTS_CSV_INVALID",
                "index_constituents.csv cannot be normalized into membership snapshots.",
                {"error": f"{type(exc).__name__}: {exc}"},
            )
        )
        files.append(_raw_summary("index_constituents", path, raw, required=False))
        return None
    normalized = pd.DataFrame(
        [
            {"index_code": row["index_code"], "date": row["date"], "symbol": symbol}
            for row in rows
            for symbol in row["symbols"]
        ]
    )
    files.append(_frame_summary("index_constituents", path, raw, normalized, required=False))
    duplicate_count = int(normalized.duplicated(["index_code", "date", "symbol"]).sum()) if not normalized.empty else 0
    if duplicate_count:
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "INDEX_CONSTITUENTS_DUPLICATE_KEYS",
                "Duplicate index constituent rows will be de-duplicated during import.",
                {"duplicate_count": duplicate_count},
            )
        )
    return normalized


def _cross_validate_tables(
    *,
    bars: pd.DataFrame | None,
    stock_info: pd.DataFrame | None,
    fundamentals: pd.DataFrame | None,
    calendar: list[str] | None,
    suspensions: pd.DataFrame | None,
    index_constituents: pd.DataFrame | None,
    findings: list[CSVValidationFinding],
    metrics: dict[str, Any],
) -> None:
    if bars is None or bars.empty:
        return
    bar_symbols = set(bars["symbol"].astype(str))
    if stock_info is not None and not stock_info.empty:
        stock_symbols = set(stock_info["symbol"].astype(str))
        missing_stock_info = sorted(bar_symbols - stock_symbols)
        if missing_stock_info:
            findings.append(
                CSVValidationFinding(
                    "WATCH",
                    "STOCK_INFO_SYMBOL_GAP",
                    "Some bar symbols do not have stock_info rows.",
                    {"missing_count": len(missing_stock_info), "examples": missing_stock_info[:10]},
                )
            )
        metrics["stock_info_symbol_count"] = len(stock_symbols)
        metrics["stock_info_st_count"] = int(
            pd.to_numeric(stock_info.get("is_st", pd.Series(dtype=int)), errors="coerce")
            .fillna(0)
            .eq(1)
            .sum()
        )
    if fundamentals is not None and not fundamentals.empty:
        fundamental_symbols = set(fundamentals["symbol"].astype(str))
        missing_fundamentals = sorted(bar_symbols - fundamental_symbols)
        if missing_fundamentals:
            findings.append(
                CSVValidationFinding(
                    "WATCH",
                    "FUNDAMENTALS_SYMBOL_GAP",
                    "Some bar symbols do not have fundamentals rows.",
                    {"missing_count": len(missing_fundamentals), "examples": missing_fundamentals[:10]},
                )
            )
        metrics["fundamentals_symbol_count"] = len(fundamental_symbols)
    if calendar:
        _validate_calendar_coverage(bars, calendar, findings, metrics)
    if suspensions is not None and not suspensions.empty:
        suspension_symbols = set(suspensions["symbol"].astype(str))
        missing_suspension_symbols = sorted(suspension_symbols - bar_symbols)
        if missing_suspension_symbols:
            findings.append(
                CSVValidationFinding(
                    "WATCH",
                    "SUSPENSIONS_SYMBOL_GAP",
                    "Some suspension symbols do not appear in bars.csv.",
                    {"missing_count": len(missing_suspension_symbols), "examples": missing_suspension_symbols[:10]},
                )
            )
        metrics["suspension_symbol_count"] = len(suspension_symbols)
        metrics["suspension_row_count"] = len(suspensions)
        metrics["suspended_symbol_day_count"] = int(
            pd.to_numeric(suspensions.get("is_suspended", pd.Series(dtype=int)), errors="coerce")
            .fillna(0)
            .eq(1)
            .sum()
        )
    if index_constituents is not None and not index_constituents.empty:
        constituent_symbols = set(index_constituents["symbol"].astype(str))
        missing_constituents = sorted(constituent_symbols - bar_symbols)
        if missing_constituents:
            findings.append(
                CSVValidationFinding(
                    "WATCH",
                    "INDEX_CONSTITUENTS_SYMBOL_GAP",
                    "Some index constituent symbols do not appear in bars.csv.",
                    {"missing_count": len(missing_constituents), "examples": missing_constituents[:10]},
                )
            )
        metrics["index_constituent_symbol_count"] = len(constituent_symbols)
        metrics["index_constituent_snapshot_count"] = int(
            index_constituents.drop_duplicates(["index_code", "date"]).shape[0]
        )


def _validate_calendar_coverage(
    bars: pd.DataFrame,
    calendar: list[str],
    findings: list[CSVValidationFinding],
    metrics: dict[str, Any],
) -> None:
    bar_dates = set(bars["date"].astype(str))
    first_date = str(bars["date"].min())
    last_date = str(bars["date"].max())
    relevant_days = [day for day in calendar if first_date <= day <= last_date]
    empty_open_days = sorted(set(relevant_days) - bar_dates)
    if empty_open_days:
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "CALENDAR_OPEN_DAY_WITHOUT_BARS",
                "Some open calendar dates have no bars for any symbol.",
                {"missing_day_count": len(empty_open_days), "examples": empty_open_days[:10]},
            )
        )
    symbols = set(bars["symbol"].astype(str))
    expected = len(symbols) * len(relevant_days)
    observed = int(bars.drop_duplicates(["symbol", "date"]).shape[0])
    missing = max(expected - observed, 0)
    missing_ratio = missing / expected if expected else 0.0
    metrics.update(
        {
            "calendar_open_days_in_bar_range": len(relevant_days),
            "expected_symbol_day_rows": expected,
            "observed_symbol_day_rows": observed,
            "missing_symbol_day_rows": missing,
            "missing_symbol_day_ratio": round(missing_ratio, 6),
        }
    )
    if missing_ratio > 0.10:
        findings.append(
            CSVValidationFinding(
                "BLOCK",
                "CALENDAR_COVERAGE_BLOCK",
                "More than 10% of expected symbol-day rows are missing against calendar.csv.",
                {"missing_ratio": round(missing_ratio, 6), "missing_rows": missing},
            )
        )
    elif missing:
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "CALENDAR_COVERAGE_GAP",
                "Some expected symbol-day rows are missing against calendar.csv.",
                {"missing_ratio": round(missing_ratio, 6), "missing_rows": missing},
            )
        )


def _raw_summary(role: str, path: Path, raw: pd.DataFrame, *, required: bool) -> CSVFileSummary:
    file_version = _file_version(path)
    return CSVFileSummary(
        role=role,
        path=str(path),
        required=required,
        exists=True,
        size_bytes=file_version["size_bytes"],
        sha256=file_version["sha256"],
        modified_at_utc=file_version["modified_at_utc"],
        columns=[str(column) for column in raw.columns],
        row_count=len(raw),
        normalized_row_count=0,
    )


def _frame_summary(
    role: str,
    path: Path,
    raw: pd.DataFrame,
    normalized: pd.DataFrame,
    *,
    required: bool,
) -> CSVFileSummary:
    file_version = _file_version(path)
    symbol_count = int(normalized["symbol"].nunique()) if "symbol" in normalized else 0
    start = str(normalized["date"].min()) if "date" in normalized and not normalized.empty else ""
    end = str(normalized["date"].max()) if "date" in normalized and not normalized.empty else ""
    return CSVFileSummary(
        role=role,
        path=str(path),
        required=required,
        exists=True,
        size_bytes=file_version["size_bytes"],
        sha256=file_version["sha256"],
        modified_at_utc=file_version["modified_at_utc"],
        columns=[str(column) for column in raw.columns],
        row_count=len(raw),
        normalized_row_count=len(normalized),
        symbol_count=symbol_count,
        start=start,
        end=end,
    )


def _missing_file_summary(role: str, path: Path, *, required: bool) -> CSVFileSummary:
    return CSVFileSummary(role=role, path=str(path), required=required, exists=False)


def _file_version(path: Path) -> dict[str, int | str]:
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC).replace(microsecond=0).isoformat()
    return {
        "size_bytes": stat.st_size,
        "sha256": _sha256(path),
        "modified_at_utc": modified,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dataset_fingerprint(files: list[CSVFileSummary]) -> str:
    digest = hashlib.sha256()
    for item in sorted((file for file in files if file.exists and file.sha256), key=lambda f: f.role):
        digest.update(item.role.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.sha256.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest() if digest.digest() != hashlib.sha256().digest() else ""


def _invalid_ohlc_count(bars: pd.DataFrame) -> int:
    prices = bars[["open", "high", "low", "close"]].astype(float)
    invalid = (
        (prices <= 0).any(axis=1)
        | (bars["high"] < bars[["open", "close"]].max(axis=1))
        | (bars["low"] > bars[["open", "close"]].min(axis=1))
        | (bars["low"] > bars["high"])
    )
    return int(invalid.sum())


def _calendar_day_lag(actual_end: str, expected_end: str) -> int | None:
    try:
        return (pd.Timestamp(expected_end).date() - pd.Timestamp(actual_end).date()).days
    except (TypeError, ValueError):
        return None


def _combine_status(findings: list[CSVValidationFinding]) -> CSVStatus:
    if any(finding.severity == "BLOCK" for finding in findings):
        return "BLOCK"
    if any(finding.severity == "WATCH" for finding in findings):
        return "WATCH"
    return "PASS"


def _templates_readme() -> str:
    return "\n".join(
        [
            "# Offline Research CSV Templates",
            "",
            "These files are examples only. Replace sample rows with broker or data-vendor exports.",
            "",
            "- `bars.csv` is required.",
            "- `stock_info.csv`, `fundamentals.csv`, `calendar.csv`, `suspensions.csv`, and `index_constituents.csv` are recommended.",
            "- Run `examples/validate_research_csv.py` before importing into SQLite.",
            "- A validation PASS is not investment approval; bootstrap, data audit, and review gates still apply.",
            "",
        ]
    )
