"""Research-grade A-share data importer via AKShare.

This importer is intentionally conservative: failures are recorded explicitly
and never converted into demo data. A report is always written so downstream
gates can distinguish real imported data from tutorial fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from quantify.data.akshare_compat import ak
from quantify.data.akshare_feed import AkshareFeed
from quantify.data.storage import BarStorage


@dataclass(frozen=True, slots=True)
class ImportFailure:
    symbol: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"symbol": self.symbol, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class ResearchImportReport:
    status: str
    start: str
    end: str
    cache_path: str
    requested_symbols: int
    imported_symbols: int
    failed_symbols: int
    bar_rows: int
    calendar_days: int
    failures: list[ImportFailure] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    failure_stage: str = ""
    network_blocked: bool = False
    recommended_route: str = ""
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "start": self.start,
            "end": self.end,
            "cache_path": self.cache_path,
            "requested_symbols": self.requested_symbols,
            "imported_symbols": self.imported_symbols,
            "failed_symbols": self.failed_symbols,
            "bar_rows": self.bar_rows,
            "calendar_days": self.calendar_days,
            "failures": [failure.to_dict() for failure in self.failures],
            "notes": self.notes,
            "metadata": self.metadata,
            "failure_stage": self.failure_stage,
            "network_blocked": self.network_blocked,
            "recommended_route": self.recommended_route,
            "next_actions": self.next_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Research Data Import: {self.status}",
            "",
            f"- Period: `{self.start}` to `{self.end}`",
            f"- Cache path: `{self.cache_path}`",
            f"- Requested symbols: {self.requested_symbols}",
            f"- Imported symbols: {self.imported_symbols}",
            f"- Failed symbols: {self.failed_symbols}",
            f"- Bar rows: {self.bar_rows}",
            f"- Calendar days: {self.calendar_days}",
            "",
            "## Notes",
        ]
        lines.extend(f"- {note}" for note in self.notes) if self.notes else lines.append("- None.")
        lines.extend(["", "## Failures"])
        if self.failures:
            lines.extend(f"- `{failure.symbol}`: {failure.reason}" for failure in self.failures[:50])
        else:
            lines.append("- None.")
        lines.extend(["", "## Metadata"])
        if self.metadata:
            for key, value in self.metadata.items():
                lines.append(f"- {key}: `{value}`")
        else:
            lines.append("- None.")
        lines.extend(["", "## Diagnostic"])
        lines.append(f"- Failure stage: `{self.failure_stage or 'none'}`")
        lines.append(f"- Network blocked: `{self.network_blocked}`")
        lines.append(f"- Recommended route: `{self.recommended_route or 'none'}`")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {action}" for action in self.next_actions) if self.next_actions else lines.append("- None.")
        return "\n".join(lines) + "\n"


def import_research_data(
    storage: BarStorage,
    start: str,
    end: str,
    *,
    limit: int = 300,
    adjust: str = "qfq",
    index_code: str = "000906",
    include_st: bool = False,
    include_bj: bool = False,
    symbols: list[str] | None = None,
) -> ResearchImportReport:
    try:
        stock_info = (
            _stock_info_from_symbols(symbols)
            if symbols
            else fetch_a_share_spot_info(include_st=include_st, include_bj=include_bj)
        )
    except Exception as exc:  # noqa: BLE001 - import reports must explain provider failures.
        reason = f"{type(exc).__name__}: {exc}"
        network_blocked = _looks_like_network_block(reason)
        return ResearchImportReport(
            status="BLOCK",
            start=start,
            end=end,
            cache_path=str(storage.db_path),
            requested_symbols=0,
            imported_symbols=0,
            failed_symbols=0,
            bar_rows=0,
            calendar_days=0,
            failures=[ImportFailure("symbol_list", reason)],
            notes=["Failed before symbol import; no demo data was generated."],
            metadata=_failure_metadata(
                failure_stage="symbol_list",
                network_blocked=network_blocked,
                requested_start=start,
                requested_end=end,
            ),
            failure_stage="symbol_list",
            network_blocked=network_blocked,
            recommended_route=_recommended_route(network_blocked),
            next_actions=_next_actions_for_failure(network_blocked=network_blocked, stage="symbol_list"),
        )
    if stock_info.empty:
        return ResearchImportReport(
            status="BLOCK",
            start=start,
            end=end,
            cache_path=str(storage.db_path),
            requested_symbols=0,
            imported_symbols=0,
            failed_symbols=0,
            bar_rows=0,
            calendar_days=0,
            notes=["AKShare returned no A-share spot symbols."],
            metadata=_failure_metadata(
                failure_stage="symbol_list",
                network_blocked=False,
                requested_start=start,
                requested_end=end,
            ),
            failure_stage="symbol_list",
            recommended_route="offline_csv_or_tdx",
            next_actions=_next_actions_for_failure(network_blocked=False, stage="symbol_list"),
        )

    selected = stock_info.head(limit).copy()
    storage.save_stock_info(selected)
    symbols = selected["symbol"].astype(str).tolist()
    if symbols:
        storage.save_index_constituents(index_code, start, symbols)

    feed = AkshareFeed(storage=storage, adjust=adjust)
    failures: list[ImportFailure] = []
    frames: list[pd.DataFrame] = []
    for idx, symbol in enumerate(symbols, start=1):
        try:
            frame = feed.fetch(symbol, start, end)
            if frame.empty:
                failures.append(ImportFailure(symbol, "empty bars"))
                continue
            frames.append(frame)
            logger.info("Imported {}/{} {}", idx, len(symbols), symbol)
        except Exception as exc:  # noqa: BLE001 - import should continue per symbol.
            failures.append(ImportFailure(symbol, f"{type(exc).__name__}: {exc}"))
            logger.warning("Import failed for {}: {}", symbol, exc)

    merged = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not merged.empty:
        storage.save_calendar(sorted(merged["date"].dropna().astype(str).unique().tolist()))
    status = "PASS"
    if not frames:
        status = "BLOCK"
    elif failures:
        status = "WATCH"

    network_blocked = any(_looks_like_network_block(failure.reason) for failure in failures)
    failure_stage = "bars" if failures and not frames else ""
    metadata = (
        _failure_metadata(
            failure_stage=failure_stage,
            network_blocked=network_blocked,
            requested_start=start,
            requested_end=end,
        )
        if status == "BLOCK"
        else _coverage_metadata(merged)
    )
    return ResearchImportReport(
        status=status,
        start=start,
        end=end,
        cache_path=str(storage.db_path),
        requested_symbols=len(symbols),
        imported_symbols=len({str(frame["symbol"].iloc[0]) for frame in frames if not frame.empty}),
        failed_symbols=len(failures),
        bar_rows=len(merged),
        calendar_days=int(merged["date"].nunique()) if not merged.empty else 0,
        failures=failures,
        notes=_import_notes(status, network_blocked=network_blocked),
        metadata=metadata,
        failure_stage=failure_stage,
        network_blocked=network_blocked,
        recommended_route=_recommended_route(network_blocked) if status != "PASS" else "",
        next_actions=_next_actions_for_failure(network_blocked=network_blocked, stage=failure_stage)
        if status != "PASS"
        else ["Run real_data_bootstrap on the imported cache before any strategy research."],
    )


def write_import_report(report: ResearchImportReport, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "data_import.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "data_import.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def fetch_a_share_spot_info(*, include_st: bool, include_bj: bool) -> pd.DataFrame:
    raw = ak.stock_zh_a_spot_em()
    if raw.empty:
        return pd.DataFrame(columns=["symbol", "name", "exchange", "list_date", "delist_date", "industry", "is_st"])
    symbol_col = _first_existing(raw, ["代码", "code", "symbol"])
    name_col = _first_existing(raw, ["名称", "name"])
    if symbol_col is None or name_col is None:
        raise ValueError("AKShare spot data is missing code/name columns")
    frame = pd.DataFrame(
        {
            "symbol": raw[symbol_col].astype(str).str.zfill(6),
            "name": raw[name_col].astype(str),
        }
    )
    frame["exchange"] = frame["symbol"].map(_exchange)
    frame["list_date"] = ""
    frame["delist_date"] = ""
    frame["industry"] = ""
    frame["is_st"] = frame["name"].str.upper().str.contains("ST", regex=False).astype(int)
    if not include_st:
        frame = frame[frame["is_st"] == 0]
    if not include_bj:
        frame = frame[frame["exchange"] != "BJSE"]
    return frame.drop_duplicates("symbol").sort_values("symbol").reset_index(drop=True)


def _stock_info_from_symbols(symbols: list[str]) -> pd.DataFrame:
    clean = [str(symbol).strip().zfill(6) for symbol in symbols if str(symbol).strip()]
    frame = pd.DataFrame({"symbol": clean})
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "name", "exchange", "list_date", "delist_date", "industry", "is_st"])
    frame["name"] = ""
    frame["exchange"] = frame["symbol"].map(_exchange)
    frame["list_date"] = ""
    frame["delist_date"] = ""
    frame["industry"] = ""
    frame["is_st"] = 0
    return frame.drop_duplicates("symbol").sort_values("symbol").reset_index(drop=True)


def _coverage_metadata(bars: pd.DataFrame) -> dict[str, Any]:
    if bars.empty or "date" not in bars:
        return {
            "actual_bar_start": "",
            "actual_bar_end": "",
            "actual_bar_symbol_count": 0,
        }
    dates = bars["date"].dropna().astype(str)
    return {
        "actual_bar_start": str(dates.min()) if not dates.empty else "",
        "actual_bar_end": str(dates.max()) if not dates.empty else "",
        "actual_bar_symbol_count": int(bars["symbol"].astype(str).nunique()) if "symbol" in bars else 0,
    }


def _import_notes(status: str, *, network_blocked: bool) -> list[str]:
    if status == "PASS":
        return [
            "Data imported from AKShare and stored as real research cache.",
            "Fundamentals may still be incomplete; data_audit will report missing fields.",
        ]
    if status == "WATCH":
        return [
            "Partial AKShare bar import succeeded; failed symbols are recorded in this report.",
            "Fundamentals may still be incomplete; data_audit will report missing fields.",
        ]
    blocked_reason = (
        "provider requests were blocked by network/proxy access"
        if network_blocked
        else "all requested symbols returned failures or empty bars"
    )
    return [
        f"No usable AKShare bars were imported because {blocked_reason}; no demo data was generated.",
        "The cache is not research-ready until recent real bars are imported through AKShare, guarded offline CSV, or TDX.",
    ]


def _failure_metadata(
    *,
    failure_stage: str,
    network_blocked: bool,
    requested_start: str,
    requested_end: str,
) -> dict[str, Any]:
    return {
        "actual_bar_start": "",
        "actual_bar_end": "",
        "actual_bar_symbol_count": 0,
        "failure_stage": failure_stage,
        "network_blocked": network_blocked,
        "requested_start": requested_start,
        "requested_end": requested_end,
    }


def _looks_like_network_block(reason: str) -> bool:
    markers = [
        "proxyerror",
        "unable to connect to proxy",
        "remotedisconnected",
        "winerror 10013",
        "connectionerror",
        "failed to establish a new connection",
        "max retries exceeded",
        "temporary failure in name resolution",
        "name resolution",
        "connection refused",
    ]
    text = reason.lower()
    return any(marker in text for marker in markers)


def _recommended_route(network_blocked: bool) -> str:
    return "offline_csv_or_tdx" if network_blocked else "retry_provider_or_offline_csv"


def _next_actions_for_failure(*, network_blocked: bool, stage: str) -> list[str]:
    actions = []
    if network_blocked:
        actions.append("Use guarded offline CSV/TDX intake because AKShare network access is blocked.")
    elif stage:
        actions.append(f"Inspect provider failure at stage `{stage}` before retrying AKShare.")
    actions.extend(
        [
            "Export recent A-share daily bars through the configured research end date.",
            "Fill data_source_qa_answers.json with real vendor, terminal, adjustment, license, and review evidence.",
            "Run run_offline_data_intake.py, then rerun first-million readiness with --config.",
        ]
    )
    return actions


def _first_existing(frame: pd.DataFrame, candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in frame.columns:
            return candidate
    return None


def _exchange(symbol: str) -> str:
    if symbol.startswith(("600", "601", "603", "605", "688")):
        return "SSE"
    if symbol.startswith(("000", "001", "002", "003", "300", "301")):
        return "SZSE"
    if symbol.startswith(("8", "4", "9")):
        return "BJSE"
    return ""
