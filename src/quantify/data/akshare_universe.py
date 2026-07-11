"""Build reviewed symbol files from AKShare index constituents.

This module only prepares research input files.  It does not import bars,
approve source QA, run strategy research, or create broker instructions.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd

from quantify.data.akshare_compat import ak


PROHIBITED_ACTIONS = [
    "Do not treat a generated symbol file as source-QA approval.",
    "Do not treat index constituents as point-in-time history unless separate evidence proves it.",
    "Do not run candidate experiments until data audit, source QA, and bootstrap gates pass.",
    "Do not use this artifact as broker orders or live trading instructions.",
]


@dataclass(frozen=True, slots=True)
class AkshareUniverseReport:
    status: str
    provider: str
    source_endpoint: str
    index_code: str
    index_name: str
    constituent_date: str
    requested_limit: int
    selection_method: str
    symbol_count: int
    symbol_file: str
    stock_info_csv: str
    index_constituents_csv: str
    metadata: dict[str, Any]
    warnings: list[str]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "source_endpoint": self.source_endpoint,
            "index_code": self.index_code,
            "index_name": self.index_name,
            "constituent_date": self.constituent_date,
            "requested_limit": self.requested_limit,
            "selection_method": self.selection_method,
            "symbol_count": self.symbol_count,
            "symbol_file": self.symbol_file,
            "stock_info_csv": self.stock_info_csv,
            "index_constituents_csv": self.index_constituents_csv,
            "metadata": self.metadata,
            "warnings": self.warnings,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# AKShare Universe: {self.status}",
            "",
            f"- Provider: `{self.provider}`",
            f"- Endpoint: `{self.source_endpoint}`",
            f"- Index code: `{self.index_code}`",
            f"- Index name: `{self.index_name or 'missing'}`",
            f"- Constituent date: `{self.constituent_date or 'missing'}`",
            f"- Requested limit: {self.requested_limit}",
            f"- Selection method: `{self.selection_method}`",
            f"- Symbol count: {self.symbol_count}",
            f"- Symbol file: `{self.symbol_file}`",
            f"- Stock info CSV: `{self.stock_info_csv}`",
            f"- Index constituents CSV: `{self.index_constituents_csv}`",
            "",
            "This artifact is a research input manifest only. It does not approve data quality, "
            "source licensing, strategy performance, or trading.",
            "",
            "## Warnings",
        ]
        lines.extend(f"- {item}" for item in self.warnings) if self.warnings else lines.append("- None.")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_akshare_index_universe(
    *,
    index_code: str = "000906",
    limit: int = 300,
    output_dir: str | Path = "results/import/akshare_universe",
    symbol_file_name: str | None = None,
    stock_info_file_name: str | None = None,
    index_constituents_file_name: str | None = None,
    selection_method: str = "stratified_exchange",
) -> AkshareUniverseReport:
    raw = ak.index_stock_cons_csindex(symbol=index_code)
    normalized = _normalize_constituents(raw, index_code=index_code)
    selected = _select_constituents(normalized, limit=limit, method=selection_method)
    selection_method = _normalize_selection_method(selection_method)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    suffix = f"{index_code}_{len(selected)}"
    symbol_path = root / (symbol_file_name or f"akshare_{suffix}_symbols.txt")
    stock_info_path = root / (stock_info_file_name or f"akshare_{suffix}_stock_info.csv")
    constituents_path = root / (
        index_constituents_file_name or f"akshare_{suffix}_index_constituents.csv"
    )

    symbols = selected["symbol"].astype(str).tolist()
    symbol_path.write_text("\n".join(symbols) + "\n", encoding="utf-8")
    _stock_info_frame(selected).to_csv(stock_info_path, index=False, encoding="utf-8-sig")
    _index_constituents_frame(selected).to_csv(constituents_path, index=False, encoding="utf-8-sig")

    report = AkshareUniverseReport(
        status="PASS" if len(selected) >= min(limit, len(normalized)) and len(selected) > 0 else "BLOCK",
        provider="akshare",
        source_endpoint="index_stock_cons_csindex",
        index_code=index_code,
        index_name=str(selected["index_name"].iloc[0]) if not selected.empty else "",
        constituent_date=str(selected["date"].iloc[0]) if not selected.empty else "",
        requested_limit=limit,
        selection_method=selection_method,
        symbol_count=len(symbols),
        symbol_file=str(symbol_path),
        stock_info_csv=str(stock_info_path),
        index_constituents_csv=str(constituents_path),
        metadata={
            "raw_rows": int(len(raw)),
            "normalized_rows": int(len(normalized)),
            "raw_columns": [str(col) for col in raw.columns],
            "selection_order": _selection_order_label(selection_method),
            "full_exchange_counts": _exchange_counts(normalized),
            "exchange_counts": _exchange_counts(selected),
            "selection_quotas": _exchange_counts(selected),
        },
        warnings=_warnings_for_selection(selection_method),
        next_actions=[
            (
                ".\\.venv\\Scripts\\python.exe examples\\import_research_data.py "
                "--config config\\research_recent.yaml --cache tmp\\akshare_recent_explicit_300.db "
                f"--symbols-file {symbol_path} --limit {len(symbols)} "
                "--output-dir results\\import\\akshare_recent_explicit_300"
            ),
            "Run real_data_bootstrap, data_audit, and market_regime on the imported isolated cache.",
            "Do not promote strategy research until deterministic gates and source evidence pass.",
        ],
        prohibited_actions=PROHIBITED_ACTIONS,
    )
    write_akshare_universe_report(report, root)
    return report


def write_akshare_universe_report(report: AkshareUniverseReport, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "akshare_universe.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "akshare_universe.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _normalize_constituents(raw: pd.DataFrame, *, index_code: str) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "index_code",
                "index_name",
                "symbol",
                "name",
                "exchange",
                "_provider_order",
            ]
        )
    required = {
        "日期": "date",
        "指数代码": "index_code",
        "指数名称": "index_name",
        "成分券代码": "symbol",
        "成分券名称": "name",
        "交易所": "exchange",
    }
    missing = [col for col in required if col not in raw.columns]
    if missing:
        raise ValueError(f"CSIndex constituent payload missing columns: {missing}")
    frame = raw.rename(columns=required)[list(required.values())].copy()
    frame["_provider_order"] = range(len(frame))
    frame["symbol"] = frame["symbol"].astype(str).str.extract(r"(\d+)")[0].str.zfill(6)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    frame["index_code"] = frame["index_code"].fillna(index_code).astype(str).str.zfill(6)
    frame["name"] = frame["name"].astype(str)
    frame["exchange"] = frame["exchange"].map(_exchange_code).fillna("")
    frame = frame.dropna(subset=["symbol", "date"]).drop_duplicates("symbol")
    return frame.reset_index(drop=True)


def _select_constituents(frame: pd.DataFrame, *, limit: int, method: str) -> pd.DataFrame:
    method = _normalize_selection_method(method)
    if frame.empty:
        return frame.copy()
    limit = int(limit)
    if limit <= 0:
        return _order_constituents(frame, method).reset_index(drop=True)
    limit = min(limit, len(frame))
    if method in {"provider_order", "symbol"}:
        return _order_constituents(frame, method).head(limit).reset_index(drop=True)
    return _select_stratified_by_exchange(frame, limit=limit).reset_index(drop=True)


def _select_stratified_by_exchange(frame: pd.DataFrame, *, limit: int) -> pd.DataFrame:
    if limit >= len(frame):
        return _order_constituents(frame, "provider_order")
    groups: list[dict[str, Any]] = []
    total = len(frame)
    for exchange, group in frame.groupby("exchange", sort=False, dropna=False):
        count = len(group)
        exact = limit * count / total
        quota = int(exact)
        groups.append(
            {
                "exchange": exchange,
                "count": count,
                "quota": quota,
                "remainder": exact - quota,
                "first_order": int(group["_provider_order"].min()),
            }
        )

    remaining = limit - sum(int(group["quota"]) for group in groups)
    for group in sorted(
        groups,
        key=lambda item: (-float(item["remainder"]), -int(item["count"]), int(item["first_order"])),
    )[:remaining]:
        group["quota"] = int(group["quota"]) + 1

    pieces = []
    for group in groups:
        quota = int(group["quota"])
        if quota <= 0:
            continue
        exchange = group["exchange"]
        subset = frame[frame["exchange"] == exchange].sort_values("_provider_order").head(quota)
        pieces.append(subset)
    if not pieces:
        return frame.head(0).copy()
    return pd.concat(pieces).sort_values("_provider_order")


def _order_constituents(frame: pd.DataFrame, method: str) -> pd.DataFrame:
    if method == "symbol":
        return frame.sort_values("symbol")
    return frame.sort_values("_provider_order")


def _normalize_selection_method(method: str) -> str:
    normalized = str(method or "stratified_exchange").strip().lower().replace("-", "_")
    allowed = {"stratified_exchange", "provider_order", "symbol"}
    if normalized not in allowed:
        raise ValueError(f"Unsupported AKShare universe selection method: {method!r}")
    return normalized


def _selection_order_label(method: str) -> str:
    if method == "symbol":
        return "symbol_ascending"
    if method == "provider_order":
        return "provider_row_order"
    return "exchange_stratified_then_provider_row_order"


def _exchange_counts(frame: pd.DataFrame) -> dict[str, int]:
    if frame.empty or "exchange" not in frame:
        return {}
    counts = frame["exchange"].astype(str).value_counts().to_dict()
    return {str(key): int(value) for key, value in counts.items()}


def _warnings_for_selection(selection_method: str) -> list[str]:
    warnings = [
        "CSIndex constituents are a current snapshot from the provider, not audited point-in-time history.",
        "The generated symbol file is suitable for provider import smoke/batch testing only until source QA passes.",
    ]
    if selection_method == "stratified_exchange":
        warnings.append(
            "Limit truncation is stratified by exchange only; it is not index weight, industry, "
            "liquidity, or point-in-time representative."
        )
    elif selection_method == "provider_order":
        warnings.append(
            "Limit truncation preserves provider row order; review snapshot and provider-order bias "
            "before strategy research."
        )
    else:
        warnings.append(
            "Limit truncation sorts by symbol; this is deterministic but can create exchange and code-space bias."
        )
    return warnings


def _stock_info_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(
        {
            "symbol": frame["symbol"],
            "name": frame["name"],
            "exchange": frame["exchange"],
            "list_date": "",
            "delist_date": "",
            "industry": "",
            "is_st": frame["name"].astype(str).str.upper().str.contains("ST", regex=False).astype(int),
        }
    )
    return result


def _index_constituents_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "index_code": frame["index_code"],
            "date": frame["date"],
            "symbol": frame["symbol"],
        }
    )


def _exchange_code(value: object) -> str:
    text = str(value or "")
    if "深圳" in text or "Shenzhen" in text:
        return "SZSE"
    if "上海" in text or "Shanghai" in text:
        return "SSE"
    if "北京" in text or "Beijing" in text:
        return "BJSE"
    return text
