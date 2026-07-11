"""Import externally prepared CSV datasets into the research SQLite cache."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import pandas as pd

from quantify.data.research_importer import ImportFailure, ResearchImportReport
from quantify.data.storage import BarStorage

AUTO_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "cp936")


def import_research_csvs(
    storage: BarStorage,
    *,
    bars_csv: str | Path,
    stock_info_csv: str | Path | None = None,
    fundamentals_csv: str | Path | None = None,
    calendar_csv: str | Path | None = None,
    suspensions_csv: str | Path | None = None,
    index_constituents_csv: str | Path | None = None,
    index_code: str = "000906",
    index_date: str | None = None,
    encoding: str = "utf-8-sig",
    metadata: dict[str, Any] | None = None,
) -> ResearchImportReport:
    failures: list[ImportFailure] = []
    notes = ["Data imported from local CSV files; no network provider was used."]
    bars_path = Path(bars_csv)
    if not bars_path.exists():
        return _blocked(storage, failures=[ImportFailure("bars_csv", f"missing file: {bars_path}")])

    try:
        bars = _normalize_bars(_read_csv(bars_path, encoding))
        storage.save_bars(bars)
    except Exception as exc:  # noqa: BLE001 - report all import problems.
        return _blocked(storage, failures=[ImportFailure("bars_csv", f"{type(exc).__name__}: {exc}")])

    symbols = sorted(bars["symbol"].astype(str).unique().tolist())
    if stock_info_csv:
        try:
            stock_info = _normalize_stock_info(_read_csv(stock_info_csv, encoding))
            storage.save_stock_info(stock_info)
        except Exception as exc:  # noqa: BLE001
            failures.append(ImportFailure("stock_info_csv", f"{type(exc).__name__}: {exc}"))
    else:
        storage.save_stock_info(_default_stock_info(symbols))
        notes.append("No stock_info_csv supplied; default stock_info rows were generated.")

    if fundamentals_csv:
        try:
            fundamentals = _normalize_fundamentals(_read_csv(fundamentals_csv, encoding))
            storage.save_fundamentals(fundamentals)
        except Exception as exc:  # noqa: BLE001
            failures.append(ImportFailure("fundamentals_csv", f"{type(exc).__name__}: {exc}"))
    else:
        notes.append("No fundamentals_csv supplied; valuation/quality factors may be incomplete.")

    if calendar_csv:
        try:
            calendar = _read_calendar(_read_csv(calendar_csv, encoding))
            storage.save_calendar(calendar)
        except Exception as exc:  # noqa: BLE001
            failures.append(ImportFailure("calendar_csv", f"{type(exc).__name__}: {exc}"))
    else:
        calendar = sorted(bars["date"].astype(str).unique().tolist())
        storage.save_calendar(calendar)
        notes.append("No calendar_csv supplied; calendar was inferred from bars.")

    if suspensions_csv:
        try:
            suspensions = _normalize_suspensions(_read_csv(suspensions_csv, encoding))
            storage.save_suspensions(suspensions)
        except Exception as exc:  # noqa: BLE001
            failures.append(ImportFailure("suspensions_csv", f"{type(exc).__name__}: {exc}"))
    else:
        notes.append("No suspensions_csv supplied; suspension-aware execution gates may be incomplete.")

    if index_constituents_csv:
        try:
            for row in _read_index_constituents(
                _read_csv(index_constituents_csv, encoding),
                default_index_code=index_code,
            ):
                storage.save_index_constituents(row["index_code"], row["date"], row["symbols"])
        except Exception as exc:  # noqa: BLE001
            failures.append(ImportFailure("index_constituents_csv", f"{type(exc).__name__}: {exc}"))
    elif symbols:
        storage.save_index_constituents(index_code, index_date or str(bars["date"].min()), symbols)
        notes.append("No index_constituents_csv supplied; all imported symbols were used as one index snapshot.")
    import_metadata = {
        "actual_bar_start": str(bars["date"].min()),
        "actual_bar_end": str(bars["date"].max()),
        "actual_bar_symbol_count": len(symbols),
        **(metadata or {}),
    }
    if import_metadata:
        storage.save_metadata(
            {
                "last_import_source": "local_csv",
                "last_import_status": "WATCH" if failures else "PASS",
                "last_import_start": str(bars["date"].min()),
                "last_import_end": str(bars["date"].max()),
                "last_import_symbol_count": len(symbols),
                "last_import_bar_rows": len(bars),
                **import_metadata,
            }
        )

    return ResearchImportReport(
        status="WATCH" if failures else "PASS",
        start=str(bars["date"].min()),
        end=str(bars["date"].max()),
        cache_path=str(storage.db_path),
        requested_symbols=len(symbols),
        imported_symbols=len(symbols),
        failed_symbols=0,
        bar_rows=len(bars),
        calendar_days=len(set(storage.load_calendar(str(bars["date"].min()), str(bars["date"].max())))),
        failures=failures,
        notes=notes,
        metadata=import_metadata,
    )


def _read_csv(path: str | Path, encoding: str) -> pd.DataFrame:
    if encoding.lower() != "auto":
        return pd.read_csv(path, encoding=encoding)
    errors: list[str] = []
    for candidate in AUTO_ENCODINGS:
        try:
            return pd.read_csv(path, encoding=candidate)
        except UnicodeDecodeError as exc:
            errors.append(f"{candidate}: {exc}")
    raise UnicodeDecodeError(
        "auto",
        b"",
        0,
        1,
        "Could not read CSV with any candidate encoding: " + "; ".join(errors),
    )


def _blocked(storage: BarStorage, failures: list[ImportFailure]) -> ResearchImportReport:
    return ResearchImportReport(
        status="BLOCK",
        start="",
        end="",
        cache_path=str(storage.db_path),
        requested_symbols=0,
        imported_symbols=0,
        failed_symbols=0,
        bar_rows=0,
        calendar_days=0,
        failures=failures,
        notes=["CSV import failed before usable bars were stored."],
    )


def _normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    frame = _rename_columns(frame, _ALIASES)
    required = {"symbol", "date", "open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"bars_csv missing columns: {sorted(missing)}")
    if "amount" not in frame:
        frame["amount"] = 0.0
    frame["symbol"] = frame["symbol"].map(_normalize_symbol)
    frame["date"] = frame["date"].map(_normalize_date)
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close", "volume"])
    return frame[["symbol", "date", "open", "high", "low", "close", "volume", "amount"]]


def _normalize_stock_info(frame: pd.DataFrame) -> pd.DataFrame:
    frame = _rename_columns(frame, _ALIASES)
    if "symbol" not in frame:
        raise ValueError("stock_info_csv missing symbol column")
    frame["symbol"] = frame["symbol"].map(_normalize_symbol)
    if "is_st" not in frame:
        names = frame.get("name", pd.Series([""] * len(frame))).astype(str).str.upper()
        frame["is_st"] = names.str.contains("ST", regex=False).astype(int)
    else:
        frame["is_st"] = frame["is_st"].map(_normalize_flag).astype(int)
    for col in ["name", "exchange", "list_date", "delist_date", "industry"]:
        if col not in frame:
            frame[col] = ""
    return frame[["symbol", "name", "exchange", "list_date", "delist_date", "industry", "is_st"]]


def _default_stock_info(symbols: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": symbols,
            "name": "",
            "exchange": "",
            "list_date": "",
            "delist_date": "",
            "industry": "",
            "is_st": 0,
        }
    )


def _normalize_fundamentals(frame: pd.DataFrame) -> pd.DataFrame:
    frame = _rename_columns(frame, _ALIASES)
    required = {"symbol", "date"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"fundamentals_csv missing columns: {sorted(missing)}")
    frame["symbol"] = frame["symbol"].map(_normalize_symbol)
    frame["date"] = frame["date"].map(_normalize_date)
    for col in ["pe_ttm", "pb", "roe", "market_cap", "turnover_rate"]:
        if col not in frame:
            frame[col] = None
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame[["symbol", "date", "pe_ttm", "pb", "roe", "market_cap", "turnover_rate"]]


def _read_calendar(frame: pd.DataFrame) -> list[str]:
    frame = _rename_columns(frame, _ALIASES)
    if "date" not in frame:
        raise ValueError("calendar_csv missing date column")
    if "is_open" in frame:
        frame = frame[frame["is_open"].map(_normalize_flag) == 1]
    return frame["date"].map(_normalize_date).drop_duplicates().tolist()


def _normalize_suspensions(frame: pd.DataFrame) -> pd.DataFrame:
    frame = _rename_columns(frame, _ALIASES)
    required = {"symbol", "date"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"suspensions_csv missing columns: {sorted(missing)}")
    if "is_suspended" not in frame:
        frame["is_suspended"] = 1
    frame["symbol"] = frame["symbol"].map(_normalize_symbol)
    frame["date"] = frame["date"].map(_normalize_date)
    frame["is_suspended"] = frame["is_suspended"].map(_normalize_flag).astype(int)
    return frame[["symbol", "date", "is_suspended"]]


def _read_index_constituents(frame: pd.DataFrame, *, default_index_code: str) -> list[dict[str, Any]]:
    frame = _rename_columns(frame, _ALIASES)
    required = {"date", "symbol"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"index_constituents_csv missing columns: {sorted(missing)}")
    if "index_code" not in frame:
        frame["index_code"] = default_index_code
    frame["index_code"] = frame["index_code"].map(_normalize_symbol)
    frame["symbol"] = frame["symbol"].map(_normalize_symbol)
    frame["date"] = frame["date"].map(_normalize_date)
    rows = []
    for (index_code, date_value), group in frame.groupby(["index_code", "date"], sort=True):
        rows.append(
            {
                "index_code": str(index_code),
                "date": str(date_value),
                "symbols": sorted(group["symbol"].astype(str).unique().tolist()),
            }
        )
    return rows


def _rename_columns(frame: pd.DataFrame, aliases: dict[str, str]) -> pd.DataFrame:
    normalized = {column: aliases.get(_column_key(column), _column_key(column)) for column in frame.columns}
    return frame.rename(columns=normalized).copy()


def _column_key(value: object) -> str:
    text = _repair_mojibake(str(value)).strip()
    return re.sub(r"\s+", "", text)


def _repair_mojibake(text: str) -> str:
    try:
        repaired = text.encode("latin1").decode("utf-8")
    except UnicodeError:
        return text
    return repaired if _looks_more_chinese(repaired, text) else text


def _looks_more_chinese(candidate: str, original: str) -> bool:
    return _cjk_count(candidate) > _cjk_count(original) and "�" not in candidate


def _cjk_count(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def _normalize_symbol(value: object) -> str:
    text = str(value).strip().upper()
    if text.endswith(".0"):
        text = text[:-2]
    match = re.search(r"(\d{6})", text)
    if match:
        return match.group(1)
    digits = re.sub(r"\D", "", text)
    return digits.zfill(6) if digits else text


def _normalize_date(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return pd.Timestamp(value).date().isoformat()


def _normalize_flag(value: object) -> int:
    if pd.isna(value):
        return 0
    if isinstance(value, bool):
        return int(value)
    text = str(value).strip().lower()
    if text.endswith(".0"):
        text = text[:-2]
    if text in {"1", "true", "yes", "y", "是", "开市", "交易", "停牌", "st"}:
        return 1
    if text in {"0", "false", "no", "n", "否", "休市", "未停牌", "正常", "非st", "非 st"}:
        return 0
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return int(numeric) if not pd.isna(numeric) else 0


def _alias_map() -> dict[str, str]:
    groups = {
        "symbol": [
            "symbol",
            "ts_code",
            "代码",
            "证券代码",
            "股票代码",
            "成分券代码",
        ],
        "date": ["date", "trade_date", "交易日期", "日期"],
        "open": ["open", "开盘", "开盘价"],
        "high": ["high", "最高", "最高价"],
        "low": ["low", "最低", "最低价"],
        "close": ["close", "收盘", "收盘价"],
        "volume": ["volume", "vol", "成交量", "成交量(股)", "成交量(手)"],
        "amount": ["amount", "amt", "成交额", "成交金额", "成交额(元)", "成交金额(元)"],
        "name": ["name", "证券简称", "股票简称", "名称", "简称"],
        "exchange": ["exchange", "交易所", "市场"],
        "list_date": ["list_date", "上市日期"],
        "delist_date": ["delist_date", "退市日期"],
        "industry": ["industry", "行业", "所属行业"],
        "is_st": ["is_st", "是否ST", "是否 ST", "ST", "st_flag"],
        "pe_ttm": ["pe_ttm", "PE_TTM", "市盈率TTM", "市盈率_TTM", "市盈率", "PE"],
        "pb": ["pb", "PB", "市净率"],
        "roe": ["roe", "ROE", "净资产收益率"],
        "market_cap": ["market_cap", "total_mv", "总市值", "市值"],
        "turnover_rate": ["turnover_rate", "turnover", "换手率"],
        "is_open": ["is_open", "是否开市", "是否交易", "开市", "交易"],
        "is_suspended": ["is_suspended", "是否停牌", "停牌", "停牌标志"],
        "index_code": ["index_code", "指数代码", "成分指数代码"],
    }
    aliases: dict[str, str] = {}
    for canonical, names in groups.items():
        for name in names:
            aliases[_column_key(name)] = canonical
            aliases[_column_key(_to_mojibake(name))] = canonical
    return aliases


def _to_mojibake(text: str) -> str:
    try:
        return text.encode("utf-8").decode("latin1")
    except UnicodeError:
        return text


_ALIASES = _alias_map()
