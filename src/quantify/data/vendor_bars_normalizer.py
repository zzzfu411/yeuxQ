"""Normalize raw broker/vendor daily bars into the offline research bars.csv contract."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from quantify.data.csv_contract import CSVValidationFinding
from quantify.data.csv_research_importer import AUTO_ENCODINGS, _normalize_bars

NormalizationStatus = Literal["PASS", "WATCH", "BLOCK"]

_CANONICAL_COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume", "amount"]
_AMOUNT_COLUMNS = {
    "amount",
    "成交额",
    "成交金额",
    "成交额(元)",
    "成交金额(元)",
}


@dataclass(frozen=True, slots=True)
class VendorBarsNormalizationReport:
    status: NormalizationStatus
    input_path: str
    output_dir: str
    output_bars_csv: str
    encoding: str
    start: str
    end: str
    min_symbols: int
    raw_size_bytes: int = 0
    raw_sha256: str = ""
    raw_modified_at_utc: str = ""
    raw_columns: list[str] = field(default_factory=list)
    normalized_columns: list[str] = field(default_factory=lambda: list(_CANONICAL_COLUMNS))
    raw_row_count: int = 0
    normalized_row_count: int = 0
    dropped_row_count: int = 0
    filter_dropped_row_count: int = 0
    symbol_count: int = 0
    normalized_start: str = ""
    normalized_end: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    findings: list[CSVValidationFinding] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    prohibited_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "input_path": self.input_path,
            "output_dir": self.output_dir,
            "output_bars_csv": self.output_bars_csv,
            "encoding": self.encoding,
            "start": self.start,
            "end": self.end,
            "min_symbols": self.min_symbols,
            "raw_size_bytes": self.raw_size_bytes,
            "raw_sha256": self.raw_sha256,
            "raw_modified_at_utc": self.raw_modified_at_utc,
            "raw_columns": self.raw_columns,
            "normalized_columns": self.normalized_columns,
            "raw_row_count": self.raw_row_count,
            "normalized_row_count": self.normalized_row_count,
            "dropped_row_count": self.dropped_row_count,
            "filter_dropped_row_count": self.filter_dropped_row_count,
            "symbol_count": self.symbol_count,
            "normalized_start": self.normalized_start,
            "normalized_end": self.normalized_end,
            "metrics": self.metrics,
            "findings": [finding.to_dict() for finding in self.findings],
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Vendor Bars Normalization: {self.status}",
            "",
            f"- Input: `{self.input_path}`",
            f"- Output bars: `{self.output_bars_csv or 'not written'}`",
            f"- Encoding: `{self.encoding}`",
            f"- Requested period: `{self.start or 'not specified'}` to `{self.end or 'not specified'}`",
            f"- Minimum symbols: {self.min_symbols}",
            f"- Raw size: {self.raw_size_bytes} bytes",
            f"- Raw sha256: `{self.raw_sha256 or '-'}`",
            f"- Raw modified UTC: `{self.raw_modified_at_utc or '-'}`",
            f"- Raw rows: {self.raw_row_count}",
            f"- Normalized rows: {self.normalized_row_count}",
            f"- Symbols: {self.symbol_count}",
            f"- Normalized period: `{self.normalized_start or '-'}` to `{self.normalized_end or '-'}`",
            "",
            "This report only normalizes raw broker/vendor bars into the local `bars.csv` contract. "
            "It is not source QA, CSV validation, cache import, strategy approval, or live trading permission.",
            "",
            "## Columns",
            "",
            f"- Raw: `{', '.join(self.raw_columns) or 'none'}`",
            f"- Normalized: `{', '.join(self.normalized_columns)}`",
            "",
            "## Findings",
        ]
        if self.findings:
            for finding in self.findings:
                evidence = ", ".join(
                    f"{key}={value}" for key, value in finding.evidence.items()
                )
                lines.append(
                    f"- `{finding.severity}` `{finding.code}`: {finding.message}"
                    f" ({evidence or 'n/a'})"
                )
        else:
            lines.append("- No normalization findings.")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def normalize_vendor_bars(
    *,
    input_path: str | Path,
    output_dir: str | Path = "data_exports",
    encoding: str = "utf-8-sig",
    start: str | None = None,
    end: str | None = None,
    min_symbols: int = 300,
    write_output: bool = True,
) -> VendorBarsNormalizationReport:
    """Normalize a raw daily bars CSV into data_exports/bars.csv when usable."""
    source = Path(input_path)
    root = Path(output_dir)
    output_bars = root / "bars.csv"
    findings: list[CSVValidationFinding] = []
    prohibited = _prohibited_actions()

    if not source.exists():
        findings.append(
            CSVValidationFinding(
                "BLOCK",
                "RAW_VENDOR_BARS_MISSING",
                "Raw broker/vendor bars CSV does not exist.",
                {"path": str(source)},
            )
        )
        return _report(
            input_path=source,
            output_dir=root,
            output_bars=None,
            encoding=encoding,
            start=start,
            end=end,
            min_symbols=min_symbols,
            findings=findings,
            next_actions=["Provide a raw broker/vendor daily bars CSV, then rerun normalization."],
            prohibited_actions=prohibited,
        )

    raw_version = _file_version(source)
    resolved_encoding = encoding
    try:
        raw, resolved_encoding = _read_raw_bars_csv(source, encoding=encoding)
    except UnicodeDecodeError as exc:
        findings.append(
            CSVValidationFinding(
                "BLOCK",
                "RAW_VENDOR_BARS_ENCODING_ERROR",
                "Raw bars CSV could not be read with the supplied encoding.",
                {
                    "error": str(exc),
                    "encoding": encoding,
                    "candidate_encodings": list(AUTO_ENCODINGS) if encoding.lower() == "auto" else [encoding],
                },
            )
        )
        return _report(
            input_path=source,
            output_dir=root,
            output_bars=None,
            encoding=resolved_encoding,
            start=start,
            end=end,
            min_symbols=min_symbols,
            raw_version=raw_version,
            findings=findings,
            next_actions=["Retry with --encoding auto, gbk, gb18030, or utf-8-sig after confirming the export encoding."],
            prohibited_actions=prohibited,
        )
    except Exception as exc:  # noqa: BLE001 - user data problems should become a report.
        findings.append(
            CSVValidationFinding(
                "BLOCK",
                "RAW_VENDOR_BARS_READ_ERROR",
                "Raw bars CSV could not be read.",
                {"error": f"{type(exc).__name__}: {exc}"},
            )
        )
        return _report(
            input_path=source,
            output_dir=root,
            output_bars=None,
            encoding=resolved_encoding,
            start=start,
            end=end,
            min_symbols=min_symbols,
            raw_version=raw_version,
            findings=findings,
            next_actions=["Fix the raw CSV file, then rerun normalization."],
            prohibited_actions=prohibited,
        )

    raw_columns = [str(column) for column in raw.columns]
    if not _has_amount_column(raw_columns):
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "RAW_VENDOR_BARS_AMOUNT_MISSING",
                "Raw bars CSV has no amount column; normalized bars.csv will fill amount=0.",
            )
        )
    try:
        normalized = _normalize_bars(raw)
    except Exception as exc:  # noqa: BLE001 - keep CLI report-first.
        findings.append(
            CSVValidationFinding(
                "BLOCK",
                "RAW_VENDOR_BARS_INVALID",
                "Raw bars CSV cannot be normalized into the bars.csv contract.",
                {"error": f"{type(exc).__name__}: {exc}"},
            )
        )
        return _report(
            input_path=source,
            output_dir=root,
            output_bars=None,
            encoding=resolved_encoding,
            start=start,
            end=end,
            min_symbols=min_symbols,
            raw_version=raw_version,
            raw_columns=raw_columns,
            raw_row_count=len(raw),
            findings=findings,
            next_actions=["Fix missing or unrecognized symbol/date/OHLCV columns, then rerun normalization."],
            prohibited_actions=prohibited,
        )

    dropped = len(raw) - len(normalized)
    if dropped:
        findings.append(
            CSVValidationFinding(
                "BLOCK",
                "RAW_VENDOR_BARS_ROWS_DROPPED",
                "Some rows have missing or non-numeric core OHLCV fields.",
                {"dropped_rows": dropped},
            )
        )
    filtered = _filter_period(normalized, start=start, end=end)
    filter_dropped = len(normalized) - len(filtered)
    _add_quality_findings(
        filtered,
        findings,
        start=start,
        end=end,
        min_symbols=min_symbols,
    )
    status = _combine_status(findings)
    written_bars = output_bars if status != "BLOCK" and write_output else None
    if status != "BLOCK" and write_output:
        root.mkdir(parents=True, exist_ok=True)
        filtered.loc[:, _CANONICAL_COLUMNS].to_csv(output_bars, index=False, encoding="utf-8-sig")

    return _report(
        input_path=source,
        output_dir=root,
        output_bars=written_bars,
        encoding=resolved_encoding,
        start=start,
        end=end,
        min_symbols=min_symbols,
        raw_version=raw_version,
        raw_columns=raw_columns,
        raw_row_count=len(raw),
        normalized=filtered,
        dropped_row_count=dropped,
        filter_dropped_row_count=filter_dropped,
        findings=findings,
        next_actions=_next_actions(status, output_bars),
        prohibited_actions=prohibited,
    )


def write_vendor_bars_normalization_report(
    report: VendorBarsNormalizationReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "vendor_bars_normalization.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "vendor_bars_normalization.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _read_raw_bars_csv(path: Path, *, encoding: str) -> tuple[pd.DataFrame, str]:
    if encoding.lower() != "auto":
        return pd.read_csv(path, encoding=encoding), encoding
    errors: list[str] = []
    for candidate in AUTO_ENCODINGS:
        try:
            return pd.read_csv(path, encoding=candidate), candidate
        except UnicodeDecodeError as exc:
            errors.append(f"{candidate}: {exc}")
    raise UnicodeDecodeError(
        "auto",
        b"",
        0,
        1,
        "Could not read raw bars CSV with any candidate encoding: " + "; ".join(errors),
    )


def _report(
    *,
    input_path: Path,
    output_dir: Path,
    output_bars: Path | None,
    encoding: str,
    start: str | None,
    end: str | None,
    min_symbols: int,
    raw_version: dict[str, int | str] | None = None,
    raw_columns: list[str] | None = None,
    raw_row_count: int = 0,
    normalized: pd.DataFrame | None = None,
    dropped_row_count: int = 0,
    filter_dropped_row_count: int = 0,
    findings: list[CSVValidationFinding],
    next_actions: list[str],
    prohibited_actions: list[str],
) -> VendorBarsNormalizationReport:
    bars = normalized if normalized is not None else pd.DataFrame(columns=_CANONICAL_COLUMNS)
    metrics = _metrics(bars)
    version = raw_version or {}
    return VendorBarsNormalizationReport(
        status=_combine_status(findings),
        input_path=str(input_path),
        output_dir=str(output_dir),
        output_bars_csv=str(output_bars) if output_bars is not None else "",
        encoding=encoding,
        start=start or "",
        end=end or "",
        min_symbols=min_symbols,
        raw_size_bytes=int(version.get("size_bytes", 0)),
        raw_sha256=str(version.get("sha256", "")),
        raw_modified_at_utc=str(version.get("modified_at_utc", "")),
        raw_columns=raw_columns or [],
        raw_row_count=raw_row_count,
        normalized_row_count=len(bars),
        dropped_row_count=dropped_row_count,
        filter_dropped_row_count=filter_dropped_row_count,
        symbol_count=int(bars["symbol"].nunique()) if "symbol" in bars and not bars.empty else 0,
        normalized_start=str(bars["date"].min()) if "date" in bars and not bars.empty else "",
        normalized_end=str(bars["date"].max()) if "date" in bars and not bars.empty else "",
        metrics=metrics,
        findings=findings,
        next_actions=next_actions,
        prohibited_actions=prohibited_actions,
    )


def _filter_period(
    bars: pd.DataFrame,
    *,
    start: str | None,
    end: str | None,
) -> pd.DataFrame:
    filtered = bars.copy()
    if start:
        filtered = filtered[filtered["date"].astype(str) >= start]
    if end:
        filtered = filtered[filtered["date"].astype(str) <= end]
    return filtered.reset_index(drop=True)


def _add_quality_findings(
    bars: pd.DataFrame,
    findings: list[CSVValidationFinding],
    *,
    start: str | None,
    end: str | None,
    min_symbols: int,
) -> None:
    if bars.empty:
        findings.append(
            CSVValidationFinding(
                "BLOCK",
                "NORMALIZED_VENDOR_BARS_EMPTY",
                "No usable bar rows remain after normalization and period filtering.",
            )
        )
        return
    duplicate_count = int(bars.duplicated(["symbol", "date"]).sum())
    if duplicate_count:
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "NORMALIZED_VENDOR_BARS_DUPLICATE_KEYS",
                "Duplicate symbol/date rows remain in normalized bars.csv.",
                {"duplicate_count": duplicate_count},
            )
        )
    invalid_ohlc = _invalid_ohlc_count(bars)
    if invalid_ohlc:
        findings.append(
            CSVValidationFinding(
                "BLOCK",
                "NORMALIZED_VENDOR_BARS_INVALID_OHLC",
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
                "NORMALIZED_VENDOR_BARS_NON_POSITIVE_LIQUIDITY",
                "Some rows have non-positive volume or amount.",
                {
                    "non_positive_volume_count": non_positive_volume,
                    "non_positive_amount_count": non_positive_amount,
                },
            )
        )
    symbol_count = int(bars["symbol"].nunique())
    if symbol_count < min_symbols:
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "NORMALIZED_VENDOR_BARS_SYMBOL_COUNT_BELOW_TARGET",
                "The normalized universe is below the configured recent-research target.",
                {"symbol_count": symbol_count, "min_symbols": min_symbols},
            )
        )
    first_date = str(bars["date"].min())
    last_date = str(bars["date"].max())
    if start and first_date > start:
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "NORMALIZED_VENDOR_BARS_START_AFTER_EXPECTED",
                "Normalized bars start after the requested research start date.",
                {"bars_start": first_date, "expected_start": start},
            )
        )
    if end and last_date < end:
        findings.append(
            CSVValidationFinding(
                "WATCH",
                "NORMALIZED_VENDOR_BARS_END_BEFORE_EXPECTED",
                "Normalized bars end before the requested research end date.",
                {"bars_end": last_date, "expected_end": end},
            )
        )


def _metrics(bars: pd.DataFrame) -> dict[str, Any]:
    if bars.empty:
        return {}
    return {
        "symbol_count": int(bars["symbol"].nunique()),
        "row_count": len(bars),
        "start": str(bars["date"].min()),
        "end": str(bars["date"].max()),
        "duplicate_key_count": int(bars.duplicated(["symbol", "date"]).sum()),
        "non_positive_volume_count": int((pd.to_numeric(bars["volume"], errors="coerce") <= 0).sum()),
        "non_positive_amount_count": int((pd.to_numeric(bars["amount"], errors="coerce") <= 0).sum()),
    }


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


def _has_amount_column(columns: list[str]) -> bool:
    return any(column.strip() in _AMOUNT_COLUMNS for column in columns)


def _invalid_ohlc_count(bars: pd.DataFrame) -> int:
    prices = bars[["open", "high", "low", "close"]].astype(float)
    invalid = (
        (prices <= 0).any(axis=1)
        | (bars["high"] < bars[["open", "close"]].max(axis=1))
        | (bars["low"] > bars[["open", "close"]].min(axis=1))
        | (bars["low"] > bars["high"])
    )
    return int(invalid.sum())


def _combine_status(findings: list[CSVValidationFinding]) -> NormalizationStatus:
    if any(finding.severity == "BLOCK" for finding in findings):
        return "BLOCK"
    if any(finding.severity == "WATCH" for finding in findings):
        return "WATCH"
    return "PASS"


def _next_actions(status: NormalizationStatus, output_bars: Path) -> list[str]:
    if status == "BLOCK":
        return [
            "Fix BLOCK findings before using the normalized bars contract.",
            "Do not run offline intake or strategy experiments from this raw CSV yet.",
        ]
    actions = [
        f"Run CSV validation against `{output_bars}` and any recommended metadata CSVs.",
        "Fill source QA answers with the real vendor/export evidence for this data batch.",
        "Run guarded offline data intake before real_data_bootstrap or strategy research.",
    ]
    if status == "WATCH":
        actions.insert(0, "Review WATCH evidence before importing this batch into the research cache.")
    return actions


def _prohibited_actions() -> list[str]:
    return [
        "Do not treat normalization PASS as source QA, CSV validation, strategy approval, or profitability evidence.",
        "Do not import normalized bars while downstream csv_validation or import doctor is BLOCK.",
        "Do not connect this workflow to a real broker or submit real orders.",
    ]
