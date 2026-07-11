"""Convert TongDaXin .day daily bar files into the offline CSV contract."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import struct
from typing import Any, Literal

import pandas as pd

TdxExportStatus = Literal["PASS", "WATCH", "BLOCK"]

_DAY_RECORD = struct.Struct("<IIIIIfII")
_BAR_COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume", "amount"]


@dataclass(frozen=True, slots=True)
class TdxDayFileSummary:
    path: str
    symbol: str
    exchange: str
    status: TdxExportStatus
    rows_read: int
    rows_written: int
    start: str
    end: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "status": self.status,
            "rows_read": self.rows_read,
            "rows_written": self.rows_written,
            "start": self.start,
            "end": self.end,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class TdxDayExportReport:
    status: TdxExportStatus
    input_dir: str
    output_dir: str
    start: str
    end: str
    bars_csv: str
    stock_info_csv: str
    calendar_csv: str
    discovered_files: int
    converted_files: int
    symbol_count: int
    row_count: int
    files: list[TdxDayFileSummary]
    failures: list[str]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "input_dir": self.input_dir,
            "output_dir": self.output_dir,
            "start": self.start,
            "end": self.end,
            "bars_csv": self.bars_csv,
            "stock_info_csv": self.stock_info_csv,
            "calendar_csv": self.calendar_csv,
            "discovered_files": self.discovered_files,
            "converted_files": self.converted_files,
            "symbol_count": self.symbol_count,
            "row_count": self.row_count,
            "files": [item.to_dict() for item in self.files],
            "failures": self.failures,
            "notes": self.notes,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# TongDaXin Day Export: {self.status}",
            "",
            f"- Input: `{self.input_dir}`",
            f"- Output: `{self.output_dir}`",
            f"- Date filter: `{self.start or 'none'}` to `{self.end or 'none'}`",
            f"- Bars CSV: `{self.bars_csv}`",
            f"- Stock info CSV: `{self.stock_info_csv or 'not written'}`",
            f"- Calendar CSV: `{self.calendar_csv or 'not written'}`",
            f"- Discovered files: {self.discovered_files}",
            f"- Converted files: {self.converted_files}",
            f"- Symbols: {self.symbol_count}",
            f"- Rows: {self.row_count}",
            "",
            "This is a local file conversion report, not a strategy recommendation or trading instruction.",
            "",
            "## Files",
            "",
            "| symbol | exchange | status | rows read | rows written | period | path | message |",
            "| --- | --- | --- | ---: | ---: | --- | --- | --- |",
        ]
        for item in self.files[:200]:
            period = f"{item.start or '-'} to {item.end or '-'}"
            lines.append(
                f"| `{item.symbol}` | `{item.exchange}` | `{item.status}` | "
                f"{item.rows_read} | {item.rows_written} | `{period}` | `{item.path}` | {item.message} |"
            )
        if len(self.files) > 200:
            lines.append(f"| ... | ... | ... | ... | ... | ... | ... | {len(self.files) - 200} more files omitted. |")
        lines.extend(["", "## Failures"])
        lines.extend(f"- {item}" for item in self.failures) if self.failures else lines.append("- None.")
        lines.extend(["", "## Notes"])
        lines.extend(f"- {item}" for item in self.notes)
        return "\n".join(lines) + "\n"


def export_tdx_day_to_csv(
    *,
    input_dir: str | Path,
    output_dir: str | Path = "data_exports",
    start: str | None = None,
    end: str | None = None,
    symbols: list[str] | None = None,
    include_indices: bool = False,
    write_stock_info: bool = True,
    write_calendar: bool = True,
) -> TdxDayExportReport:
    """Convert TongDaXin .day files into bars.csv plus lightweight metadata CSVs."""
    root = Path(input_dir)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    symbol_filter = {_normalize_symbol(symbol) for symbol in symbols or [] if str(symbol).strip()}
    day_files = _discover_day_files(root)
    selected_files = [
        path
        for path in day_files
        if _file_identity(path).get("symbol")
        and (not symbol_filter or _file_identity(path)["symbol"] in symbol_filter)
        and (include_indices or _is_a_share_stock(_file_identity(path)["symbol"], _file_identity(path)["exchange"]))
    ]

    rows: list[dict[str, Any]] = []
    files: list[TdxDayFileSummary] = []
    failures: list[str] = []
    for path in selected_files:
        identity = _file_identity(path)
        try:
            parsed_rows, rows_read = _read_day_file(path, start=start, end=end)
        except ValueError as exc:
            failures.append(f"{path}: {exc}")
            files.append(
                TdxDayFileSummary(
                    path=str(path),
                    symbol=identity.get("symbol", ""),
                    exchange=identity.get("exchange", ""),
                    status="BLOCK",
                    rows_read=0,
                    rows_written=0,
                    start="",
                    end="",
                    message=str(exc),
                )
            )
            continue
        for row in parsed_rows:
            row["symbol"] = identity["symbol"]
        rows.extend(parsed_rows)
        files.append(
            TdxDayFileSummary(
                path=str(path),
                symbol=identity["symbol"],
                exchange=identity["exchange"],
                status="PASS" if parsed_rows else "WATCH",
                rows_read=rows_read,
                rows_written=len(parsed_rows),
                start=str(parsed_rows[0]["date"]) if parsed_rows else "",
                end=str(parsed_rows[-1]["date"]) if parsed_rows else "",
                message="Converted." if parsed_rows else "No rows after date filter.",
            )
        )

    bars = pd.DataFrame(rows, columns=_BAR_COLUMNS)
    if not bars.empty:
        bars = bars.sort_values(["symbol", "date"]).reset_index(drop=True)
    bars_csv = out / "bars.csv"
    bars.to_csv(bars_csv, index=False)

    stock_info_csv = ""
    if write_stock_info:
        stock_info_csv = str(out / "stock_info.csv")
        _stock_info_frame(bars, files).to_csv(stock_info_csv, index=False)

    calendar_csv = ""
    if write_calendar:
        calendar_csv = str(out / "calendar.csv")
        _calendar_frame(bars).to_csv(calendar_csv, index=False)

    status = _status(row_count=len(bars), failures=failures, files=files, selected_files=selected_files)
    report = TdxDayExportReport(
        status=status,
        input_dir=str(root),
        output_dir=str(out),
        start=start or "",
        end=end or "",
        bars_csv=str(bars_csv),
        stock_info_csv=stock_info_csv,
        calendar_csv=calendar_csv,
        discovered_files=len(day_files),
        converted_files=sum(1 for item in files if item.rows_written > 0),
        symbol_count=int(bars["symbol"].nunique()) if not bars.empty else 0,
        row_count=len(bars),
        files=files,
        failures=failures,
        notes=[
            "TongDaXin .day prices are interpreted as price * 100 and divided by 100.",
            "The .day amount field is a binary float; volume is copied as stored by TongDaXin.",
            "This conversion is local-only and does not verify license, adjustment method, ST, suspensions, or point-in-time fundamentals.",
            "Fill data_source_qa_answers.json and run offline_data_package before guarded intake.",
        ],
    )
    write_tdx_day_export_report(report, out)
    return report


def write_tdx_day_export_report(report: TdxDayExportReport, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "tdx_day_export.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "tdx_day_export.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _discover_day_files(root: Path) -> list[Path]:
    if root.is_file() and root.suffix.lower() == ".day":
        return [root]
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.day") if path.is_file())


def _file_identity(path: Path) -> dict[str, str]:
    match = re.match(r"(?P<prefix>sh|sz|bj)?(?P<symbol>\d{6})\.day$", path.name.lower())
    if not match:
        return {}
    prefix = match.group("prefix") or _prefix_from_parent(path)
    return {
        "symbol": match.group("symbol"),
        "exchange": _exchange(prefix, match.group("symbol")),
    }


def _prefix_from_parent(path: Path) -> str:
    parts = [part.lower() for part in path.parts]
    if "sh" in parts:
        return "sh"
    if "sz" in parts:
        return "sz"
    if "bj" in parts:
        return "bj"
    return ""


def _exchange(prefix: str, symbol: str) -> str:
    if prefix == "sh" or symbol.startswith(("600", "601", "603", "605", "688", "689")):
        return "SSE"
    if prefix == "sz" or symbol.startswith(("000", "001", "002", "003", "300", "301")):
        return "SZSE"
    if prefix == "bj" or symbol.startswith(("4", "8", "9")):
        return "BJSE"
    return ""


def _is_a_share_stock(symbol: str, exchange: str) -> bool:
    if exchange == "SSE":
        return symbol.startswith(("600", "601", "603", "605", "688", "689"))
    if exchange == "SZSE":
        return symbol.startswith(("000", "001", "002", "003", "300", "301"))
    if exchange == "BJSE":
        return symbol.startswith(("4", "8", "9"))
    return False


def _read_day_file(path: Path, *, start: str | None, end: str | None) -> tuple[list[dict[str, Any]], int]:
    data = path.read_bytes()
    if len(data) % _DAY_RECORD.size:
        raise ValueError(f"File size {len(data)} is not a multiple of {_DAY_RECORD.size} bytes.")
    rows = []
    rows_read = 0
    for offset in range(0, len(data), _DAY_RECORD.size):
        rows_read += 1
        date_raw, open_raw, high_raw, low_raw, close_raw, amount, volume, _reserved = _DAY_RECORD.unpack_from(
            data,
            offset,
        )
        date_value = _date(date_raw)
        if not date_value:
            continue
        if start and date_value < start:
            continue
        if end and date_value > end:
            continue
        rows.append(
            {
                "date": date_value,
                "open": open_raw / 100.0,
                "high": high_raw / 100.0,
                "low": low_raw / 100.0,
                "close": close_raw / 100.0,
                "volume": int(volume),
                "amount": float(amount),
            }
        )
    return rows, rows_read


def _date(value: int) -> str:
    text = str(value)
    try:
        return datetime.strptime(text, "%Y%m%d").date().isoformat()
    except ValueError:
        return ""


def _normalize_symbol(symbol: object) -> str:
    text = str(symbol).strip().upper()
    match = re.search(r"(\d{6})", text)
    return match.group(1) if match else text.zfill(6)


def _stock_info_frame(bars: pd.DataFrame, files: list[TdxDayFileSummary]) -> pd.DataFrame:
    rows = []
    by_symbol = {item.symbol: item for item in files if item.symbol}
    symbols = sorted(bars["symbol"].unique().tolist()) if "symbol" in bars else []
    for symbol in symbols:
        summary = by_symbol.get(str(symbol))
        rows.append(
            {
                "symbol": str(symbol),
                "name": "",
                "exchange": summary.exchange if summary else "",
                "list_date": "",
                "delist_date": "",
                "industry": "",
                "is_st": 0,
            }
        )
    return pd.DataFrame(
        rows,
        columns=["symbol", "name", "exchange", "list_date", "delist_date", "industry", "is_st"],
    )


def _calendar_frame(bars: pd.DataFrame) -> pd.DataFrame:
    dates = sorted(bars["date"].unique().tolist()) if "date" in bars else []
    return pd.DataFrame({"date": dates, "is_open": [1] * len(dates)})


def _status(
    *,
    row_count: int,
    failures: list[str],
    files: list[TdxDayFileSummary],
    selected_files: list[Path],
) -> TdxExportStatus:
    if row_count <= 0 or not selected_files:
        return "BLOCK"
    if failures or any(item.status == "WATCH" for item in files):
        return "WATCH"
    return "PASS"
