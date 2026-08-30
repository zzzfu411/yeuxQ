"""A-share daily data quality audit."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from quantify.data.demo import is_demo_contaminated
from quantify.data.provider import DataProvider

AuditStatus = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class AuditFinding:
    severity: AuditStatus
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
class DataAuditReport:
    status: AuditStatus
    start: str
    end: str
    data_source: str
    cache_path: str
    symbol_count: int
    trading_day_count: int
    bar_count: int
    demo_data_used: bool
    metrics: dict[str, Any]
    findings: list[AuditFinding]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "start": self.start,
            "end": self.end,
            "data_source": self.data_source,
            "cache_path": self.cache_path,
            "symbol_count": self.symbol_count,
            "trading_day_count": self.trading_day_count,
            "bar_count": self.bar_count,
            "demo_data_used": self.demo_data_used,
            "metrics": self.metrics,
            "findings": [finding.to_dict() for finding in self.findings],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Data Audit: {self.status}",
            "",
            f"- Period: `{self.start}` to `{self.end}`",
            f"- Data source: `{self.data_source}`",
            f"- Cache path: `{self.cache_path}`",
            f"- Symbols: {self.symbol_count}",
            f"- Trading days: {self.trading_day_count}",
            f"- Bars: {self.bar_count}",
            f"- Demo data used: `{self.demo_data_used}`",
            "",
            "## Metrics",
        ]
        lines.extend(f"- {key}: `{value}`" for key, value in self.metrics.items())
        lines.extend(["", "## Findings"])
        if self.findings:
            for finding in self.findings:
                evidence = ", ".join(f"{k}={v}" for k, v in finding.evidence.items())
                lines.append(
                    f"- `{finding.severity}` `{finding.code}`: {finding.message}"
                    f" ({evidence or 'n/a'})"
                )
        else:
            lines.append("- No data quality findings.")
        return "\n".join(lines) + "\n"


def audit_data(
    data: DataProvider,
    start: str,
    end: str,
    *,
    data_source: str = "",
    cache_path: str = "",
    demo_data_used: bool | None = None,
) -> DataAuditReport:
    symbols = data.all_symbols()
    days = data.trading_days(start, end)
    bars = data.bars(symbols, start, end) if symbols else pd.DataFrame()
    info = data.stock_info()
    metadata = data.metadata()
    demo_like = is_demo_contaminated(symbols) or bool(demo_data_used)

    findings: list[AuditFinding] = []
    if not symbols:
        findings.append(
            AuditFinding("BLOCK", "NO_SYMBOLS", "No symbols are available in the data cache.")
        )
    if not days:
        findings.append(
            AuditFinding("BLOCK", "NO_TRADING_DAYS", "No trading days are available for the audit range.")
        )
    if bars.empty:
        findings.append(
            AuditFinding("BLOCK", "NO_BARS", "No bars are available for the audit range.")
        )

    duplicate_count = _duplicate_count(bars)
    invalid_price_count = _invalid_price_count(bars)
    non_positive_volume_count = _non_positive_count(bars, "volume")
    non_positive_amount_count = _non_positive_count(bars, "amount")
    missing_bar_count, missing_by_symbol = _missing_bars(symbols, days, bars)
    st_count, delisted_count, st_examples, delisted_examples = _stock_info_counts(info)
    suspension_count, suspension_examples = _suspension_count(data, days)
    limit_up_count, limit_down_count, limit_examples = _price_limit_counts(bars)
    missing_fundamental_count = _missing_fundamental_count(data, symbols, end)
    universe_snapshot_finding = _universe_snapshot_finding(
        metadata,
        configured_data_source=data_source,
    )

    expected_bars = len(symbols) * len(days)
    missing_ratio = missing_bar_count / expected_bars if expected_bars else 0.0
    if demo_like:
        findings.append(
            AuditFinding(
                "WATCH",
                "DEMO_DATA",
                "The audit appears to use demo data; this cannot justify micro-live readiness.",
            )
        )
    if missing_ratio > 0.10:
        findings.append(
            AuditFinding(
                "BLOCK",
                "MISSING_BARS_BLOCK",
                "More than 10% of expected symbol-day bars are missing.",
                {"missing_ratio": round(missing_ratio, 4), "missing_bar_count": missing_bar_count},
            )
        )
    elif missing_bar_count:
        findings.append(
            AuditFinding(
                "WATCH",
                "MISSING_BARS",
                "Some expected symbol-day bars are missing.",
                {"missing_ratio": round(missing_ratio, 4), "missing_bar_count": missing_bar_count},
            )
        )
    if duplicate_count:
        findings.append(
            AuditFinding(
                "WATCH",
                "DUPLICATE_BARS",
                "Duplicate symbol-date bars were found after loading data.",
                {"duplicate_count": duplicate_count},
            )
        )
    if invalid_price_count:
        findings.append(
            AuditFinding(
                "BLOCK",
                "INVALID_OHLC",
                "Invalid OHLC values were found.",
                {"invalid_price_count": invalid_price_count},
            )
        )
    if non_positive_volume_count or non_positive_amount_count:
        findings.append(
            AuditFinding(
                "WATCH",
                "NON_POSITIVE_LIQUIDITY",
                "Some bars have non-positive volume or amount.",
                {
                    "non_positive_volume_count": non_positive_volume_count,
                    "non_positive_amount_count": non_positive_amount_count,
                },
            )
        )
    if missing_fundamental_count:
        findings.append(
            AuditFinding(
                "WATCH",
                "MISSING_FUNDAMENTALS",
                "Some symbols have no latest fundamentals for the audit end date.",
                {"missing_fundamental_count": missing_fundamental_count},
            )
        )
    if universe_snapshot_finding is not None:
        findings.append(universe_snapshot_finding)
    if st_count:
        findings.append(
            AuditFinding(
                "WATCH",
                "ST_SYMBOLS_PRESENT",
                "ST symbols are present in the audited cache; deployment universes must explicitly exclude or justify them.",
                {"st_symbol_count": st_count, "examples": st_examples},
            )
        )
    if delisted_count:
        findings.append(
            AuditFinding(
                "BLOCK",
                "DELISTED_SYMBOLS_PRESENT",
                "Delisted symbols are present in the audited cache universe and cannot support micro-live readiness.",
                {"delisted_symbol_count": delisted_count, "examples": delisted_examples},
            )
        )
    if suspension_count:
        findings.append(
            AuditFinding(
                "WATCH",
                "SUSPENSIONS_PRESENT",
                "Suspension flags are present; paper execution and manual target plans must reject suspended rows.",
                {"suspension_symbol_day_count": suspension_count, "examples": suspension_examples},
            )
        )
    if limit_up_count or limit_down_count:
        findings.append(
            AuditFinding(
                "WATCH",
                "PRICE_LIMIT_EVENTS_PRESENT",
                "Price-limit-like events are present and must be treated as execution constraints in paper/manual review.",
                {
                    "limit_up_count": limit_up_count,
                    "limit_down_count": limit_down_count,
                    "examples": limit_examples,
                },
            )
        )

    metrics = {
        "expected_bar_count": expected_bars,
        "missing_bar_count": missing_bar_count,
        "missing_bar_ratio": round(missing_ratio, 6),
        "symbols_with_missing_bars": missing_by_symbol[:10],
        "duplicate_bar_count": duplicate_count,
        "invalid_price_count": invalid_price_count,
        "non_positive_volume_count": non_positive_volume_count,
        "non_positive_amount_count": non_positive_amount_count,
        "st_symbol_count": st_count,
        "delisted_symbol_count": delisted_count,
        "suspension_symbol_day_count": suspension_count,
        "limit_up_count": limit_up_count,
        "limit_down_count": limit_down_count,
        "missing_fundamental_count": missing_fundamental_count,
        "universe_snapshot_mode": metadata.get("data_import_universe_snapshot_mode", ""),
        "universe_snapshot_asof_utc": metadata.get(
            "data_import_universe_snapshot_asof_utc",
            "",
        ),
        "universe_point_in_time": _metadata_truthy(
            metadata.get("data_import_universe_point_in_time", "")
        ),
    }
    return DataAuditReport(
        status=_combine_status(findings),
        start=start,
        end=end,
        data_source=data_source,
        cache_path=cache_path,
        symbol_count=len(symbols),
        trading_day_count=len(days),
        bar_count=len(bars),
        demo_data_used=demo_like,
        metrics=metrics,
        findings=findings,
    )


def write_data_audit(report: DataAuditReport, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "data_audit.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "data_audit.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _duplicate_count(bars: pd.DataFrame) -> int:
    if bars.empty:
        return 0
    return int(bars.duplicated(["symbol", "date"]).sum())


def _invalid_price_count(bars: pd.DataFrame) -> int:
    if bars.empty:
        return 0
    prices = bars[["open", "high", "low", "close"]].astype(float)
    invalid = (
        (prices <= 0).any(axis=1)
        | (bars["high"] < bars[["open", "close"]].max(axis=1))
        | (bars["low"] > bars[["open", "close"]].min(axis=1))
        | (bars["low"] > bars["high"])
    )
    return int(invalid.sum())


def _non_positive_count(bars: pd.DataFrame, column: str) -> int:
    if bars.empty or column not in bars:
        return 0
    return int((pd.to_numeric(bars[column], errors="coerce") <= 0).sum())


def _missing_bars(
    symbols: list[str],
    days: list[str],
    bars: pd.DataFrame,
) -> tuple[int, list[dict[str, int | str]]]:
    if not symbols or not days:
        return 0, []
    counts = bars.drop_duplicates(["symbol", "date"]).groupby("symbol")["date"].count()
    rows = []
    missing_total = 0
    expected = len(days)
    for symbol in symbols:
        observed = int(counts.get(symbol, 0))
        missing = max(expected - observed, 0)
        if missing:
            missing_total += missing
            rows.append({"symbol": symbol, "missing_count": missing})
    rows.sort(key=lambda row: int(row["missing_count"]), reverse=True)
    return missing_total, rows


def _stock_info_counts(info: pd.DataFrame) -> tuple[int, int, list[dict[str, str]], list[dict[str, str]]]:
    if info.empty:
        return 0, 0, [], []
    names = info.get("name", pd.Series(dtype=str)).astype(str).str.upper()
    is_st = pd.to_numeric(info.get("is_st", pd.Series(dtype=int)), errors="coerce").fillna(0) == 1
    delisted = info.get("delist_date", pd.Series(dtype=str)).astype(str).str.strip() != ""
    st_mask = is_st | names.str.contains("ST", regex=False)
    return (
        int(st_mask.sum()),
        int(delisted.sum()),
        _stock_examples(info, st_mask, include_delist=False),
        _stock_examples(info, delisted, include_delist=True),
    )


def _suspension_count(data: DataProvider, days: list[str]) -> tuple[int, list[dict[str, str]]]:
    total = 0
    examples: list[dict[str, str]] = []
    for day in days:
        suspended = sorted(data.suspended_symbols(day))
        total += len(suspended)
        for symbol in suspended:
            if len(examples) >= 10:
                continue
            examples.append({"symbol": symbol, "date": day})
    return total, examples


def _price_limit_counts(bars: pd.DataFrame) -> tuple[int, int, list[dict[str, str | float]]]:
    if bars.empty:
        return 0, 0, []
    frame = bars.sort_values(["symbol", "date"]).copy()
    frame["prev_close"] = frame.groupby("symbol")["close"].shift(1)
    pct_change = frame["close"] / frame["prev_close"] - 1
    frame = frame.assign(pct_change=pct_change)
    limit_up = frame["pct_change"] >= 0.099
    limit_down = frame["pct_change"] <= -0.099
    examples = _limit_examples(frame[limit_up | limit_down])
    return int(limit_up.sum()), int(limit_down.sum()), examples


def _missing_fundamental_count(data: DataProvider, symbols: list[str], as_of: str) -> int:
    fundamentals = data.fundamentals(symbols, as_of)
    if fundamentals.empty:
        return len(symbols)
    return len(set(symbols) - set(fundamentals["symbol"].astype(str)))


def _universe_snapshot_finding(
    metadata: dict[str, str],
    *,
    configured_data_source: str,
) -> AuditFinding | None:
    source = str(metadata.get("data_source") or configured_data_source).strip().lower()
    mode = str(metadata.get("data_import_universe_snapshot_mode", "") or "").strip()
    point_in_time = _metadata_truthy(
        metadata.get("data_import_universe_point_in_time", "")
    )
    if point_in_time:
        return None
    if source != "akshare" and not mode:
        return None
    return AuditFinding(
        "WATCH",
        "UNIVERSE_NOT_POINT_IN_TIME",
        (
            "The research universe is a current or manual snapshot without point-in-time "
            "membership evidence; results may contain survivorship bias and remain research-only."
        ),
        {
            "data_source": source or "missing",
            "universe_snapshot_mode": mode or "missing",
            "universe_snapshot_asof_utc": metadata.get(
                "data_import_universe_snapshot_asof_utc",
                "",
            ),
            "point_in_time": False,
        },
    )


def _metadata_truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "pass"}


def _combine_status(findings: list[AuditFinding]) -> AuditStatus:
    if any(finding.severity == "BLOCK" for finding in findings):
        return "BLOCK"
    if any(finding.severity == "WATCH" for finding in findings):
        return "WATCH"
    return "PASS"


def _stock_examples(
    info: pd.DataFrame,
    mask: pd.Series,
    *,
    include_delist: bool,
) -> list[dict[str, str]]:
    examples = []
    columns = ["symbol", "name"]
    if include_delist:
        columns.append("delist_date")
    available = [column for column in columns if column in info]
    for row in info.loc[mask, available].head(10).to_dict("records"):
        examples.append({key: str(value) for key, value in row.items()})
    return examples


def _limit_examples(frame: pd.DataFrame) -> list[dict[str, str | float]]:
    if frame.empty:
        return []
    examples = []
    columns = ["symbol", "date", "close", "prev_close", "pct_change"]
    for row in frame[columns].head(10).to_dict("records"):
        examples.append(
            {
                "symbol": str(row["symbol"]),
                "date": str(row["date"]),
                "close": round(float(row["close"]), 4),
                "prev_close": round(float(row["prev_close"]), 4),
                "pct_change": round(float(row["pct_change"]), 4),
            }
        )
    return examples
