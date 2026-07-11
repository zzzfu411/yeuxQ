"""Coverage diagnostics for cached A-share daily bars."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from quantify.data.provider import DataProvider

CoverageStatus = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class DataCoverageReport:
    status: CoverageStatus
    start: str
    end: str
    symbol_count: int
    expected_trading_days: int
    latest_bar_date: str
    full_coverage_symbol_count: int
    short_history_symbol_count: int
    stale_symbol_count: int
    average_coverage_ratio: float
    findings: list[str]
    rows: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "start": self.start,
            "end": self.end,
            "symbol_count": self.symbol_count,
            "expected_trading_days": self.expected_trading_days,
            "latest_bar_date": self.latest_bar_date,
            "full_coverage_symbol_count": self.full_coverage_symbol_count,
            "short_history_symbol_count": self.short_history_symbol_count,
            "stale_symbol_count": self.stale_symbol_count,
            "average_coverage_ratio": self.average_coverage_ratio,
            "findings": self.findings,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Data Coverage Report: {self.status}",
            "",
            f"- Period: `{self.start}` to `{self.end}`",
            f"- Symbols: {self.symbol_count}",
            f"- Expected trading days: {self.expected_trading_days}",
            f"- Latest bar date: `{self.latest_bar_date or 'missing'}`",
            f"- Full-coverage symbols: {self.full_coverage_symbol_count}",
            f"- Short-history symbols: {self.short_history_symbol_count}",
            f"- Stale symbols: {self.stale_symbol_count}",
            f"- Average coverage ratio: {self.average_coverage_ratio:.2%}",
            "",
            "## Findings",
        ]
        lines.extend(f"- {finding}" for finding in self.findings) if self.findings else lines.append("- None.")
        lines.extend(["", "## Worst Coverage Samples", ""])
        lines.append("| symbol | first_date | last_date | bar_count | coverage_ratio | missing_days | stale |")
        lines.append("| --- | --- | --- | ---: | ---: | ---: | --- |")
        for row in sorted(self.rows, key=lambda item: float(item["coverage_ratio"]))[:10]:
            lines.append(
                "| {symbol} | {first} | {last} | {bars} | {ratio:.2%} | {missing} | {stale} |".format(
                    symbol=row["symbol"],
                    first=row["first_date"],
                    last=row["last_date"],
                    bars=row["bar_count"],
                    ratio=float(row["coverage_ratio"]),
                    missing=row["missing_days"],
                    stale=row["is_stale"],
                )
            )
        return "\n".join(lines) + "\n"


def analyze_data_coverage(
    data: DataProvider,
    start: str,
    end: str,
    *,
    min_coverage_ratio: float = 0.95,
    max_stale_symbols_ratio: float = 0.05,
) -> DataCoverageReport:
    symbols = data.all_symbols()
    days = data.trading_days(start, end)
    expected = len(days)
    bars = data.bars(symbols, start, end) if symbols else pd.DataFrame()
    latest = _latest_date(bars)
    rows = _coverage_rows(symbols, bars, expected, latest)
    full_count = sum(1 for row in rows if float(row["coverage_ratio"]) >= min_coverage_ratio)
    short_count = sum(1 for row in rows if float(row["coverage_ratio"]) < min_coverage_ratio)
    stale_count = sum(1 for row in rows if row["is_stale"])
    avg_ratio = sum(float(row["coverage_ratio"]) for row in rows) / len(rows) if rows else 0.0
    findings = _findings(
        symbols=symbols,
        expected=expected,
        rows=rows,
        avg_ratio=avg_ratio,
        short_count=short_count,
        stale_count=stale_count,
        min_coverage_ratio=min_coverage_ratio,
        max_stale_symbols_ratio=max_stale_symbols_ratio,
    )
    return DataCoverageReport(
        status=_status(findings),
        start=start,
        end=end,
        symbol_count=len(symbols),
        expected_trading_days=expected,
        latest_bar_date=latest,
        full_coverage_symbol_count=full_count,
        short_history_symbol_count=short_count,
        stale_symbol_count=stale_count,
        average_coverage_ratio=avg_ratio,
        findings=[finding["message"] for finding in findings],
        rows=rows,
    )


def write_data_coverage_report(report: DataCoverageReport, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "data_coverage.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "data_coverage.md").write_text(report.to_markdown(), encoding="utf-8")
    pd.DataFrame(report.rows).to_csv(root / "data_coverage.csv", index=False)
    return root


def _coverage_rows(
    symbols: list[str],
    bars: pd.DataFrame,
    expected_days: int,
    latest: str,
) -> list[dict[str, Any]]:
    if not symbols:
        return []
    if bars.empty:
        return [
            _row(symbol, "", "", 0, expected_days, latest)
            for symbol in symbols
        ]
    grouped = bars.groupby("symbol")["date"]
    rows = []
    for symbol in symbols:
        if symbol not in grouped.groups:
            rows.append(_row(symbol, "", "", 0, expected_days, latest))
            continue
        dates = grouped.get_group(symbol).astype(str)
        rows.append(_row(symbol, dates.min(), dates.max(), int(dates.nunique()), expected_days, latest))
    return rows


def _row(
    symbol: str,
    first_date: str,
    last_date: str,
    bar_count: int,
    expected_days: int,
    latest: str,
) -> dict[str, Any]:
    missing = max(expected_days - bar_count, 0)
    ratio = bar_count / expected_days if expected_days else 0.0
    return {
        "symbol": symbol,
        "first_date": first_date,
        "last_date": last_date,
        "bar_count": bar_count,
        "expected_days": expected_days,
        "missing_days": missing,
        "coverage_ratio": ratio,
        "is_stale": bool(latest and last_date and last_date < latest) or bool(latest and not last_date),
    }


def _findings(
    *,
    symbols: list[str],
    expected: int,
    rows: list[dict[str, Any]],
    avg_ratio: float,
    short_count: int,
    stale_count: int,
    min_coverage_ratio: float,
    max_stale_symbols_ratio: float,
) -> list[dict[str, str]]:
    findings = []
    if not symbols:
        findings.append({"severity": "BLOCK", "message": "No symbols are available in the cache."})
    if expected == 0:
        findings.append({"severity": "BLOCK", "message": "No trading days are available for the coverage range."})
    if rows and avg_ratio < min_coverage_ratio:
        findings.append(
            {
                "severity": "WATCH",
                "message": f"Average coverage ratio {avg_ratio:.2%} is below {min_coverage_ratio:.2%}.",
            }
        )
    if short_count:
        findings.append(
            {
                "severity": "WATCH",
                "message": f"{short_count} symbols have less than {min_coverage_ratio:.2%} coverage.",
            }
        )
    stale_ratio = stale_count / len(rows) if rows else 0.0
    if stale_ratio > max_stale_symbols_ratio:
        findings.append(
            {
                "severity": "WATCH",
                "message": f"{stale_count} symbols are stale relative to the latest cached bar date.",
            }
        )
    return findings


def _status(findings: list[dict[str, str]]) -> CoverageStatus:
    if any(finding["severity"] == "BLOCK" for finding in findings):
        return "BLOCK"
    if any(finding["severity"] == "WATCH" for finding in findings):
        return "WATCH"
    return "PASS"


def _latest_date(bars: pd.DataFrame) -> str:
    if bars.empty or "date" not in bars:
        return ""
    values = pd.to_datetime(bars["date"], errors="coerce").dropna()
    if values.empty:
        return ""
    return values.max().date().isoformat()
