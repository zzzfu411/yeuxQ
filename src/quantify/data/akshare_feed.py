"""AKShare data feed for A-share daily bars.

AKShare is free, requires no token, and is the most accessible A-share data source
for Chinese users. It returns Chinese column names which we normalize to canonical
English names here.

Caching strategy:
    On `fetch`, we first check the local SQLite cache for the latest date stored
    for the symbol. If the cache already covers the requested range, we skip the
    network call. Otherwise we pull from AKShare and upsert into the cache.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timedelta

import pandas as pd
from loguru import logger

from quantify.core.bar import Bar
from quantify.data.akshare_compat import ak
from quantify.data.base import DataFeed
from quantify.data.storage import BarStorage

# AKShare 中文列名 → 我们的标准英文列名
_COLUMN_MAP = {
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
}


class AkshareFeed(DataFeed):
    """A-share daily bars via AKShare, cached in local SQLite."""

    def __init__(
        self,
        storage: BarStorage | None,
        adjust: str = "qfq",
        *,
        persist: bool = True,
    ) -> None:
        """
        Args:
            storage: BarStorage instance for cache.
            adjust:  '' / 'qfq' / 'hfq' — 不复权 / 前复权 / 后复权.
                     Default 前复权(qfq):适合多数策略回测,避免分红送股导致价格跳变。
        """
        self.storage = storage
        if persist and storage is None:
            raise ValueError("storage is required when persist=True")
        if adjust not in ("", "qfq", "hfq"):
            raise ValueError(f"adjust must be '', 'qfq' or 'hfq', got {adjust!r}")
        self.adjust = adjust
        self.persist = persist
        self.fetch_routes: dict[str, str] = {}

    def fetch(
        self,
        symbol: str,
        start: str | date,
        end: str | date,
    ) -> pd.DataFrame:
        """Download bars from AKShare and upsert into cache."""
        start_str = _to_akshare_date(start)
        end_str = _to_akshare_date(end)

        logger.info(
            "Fetching {} from AKShare: {} ~ {} adjust={}",
            symbol, start_str, end_str, self.adjust or "raw",
        )
        # AKShare 日线接口签名:
        # stock_zh_a_hist(symbol, period, start_date, end_date, adjust)
        # symbol 形如 "600519"(沪市) / "000001"(深市) / "300750"(创业板)
        raw, route = self._fetch_raw(symbol, start_str, end_str)
        if raw.empty:
            logger.warning("AKShare returned 0 rows for {} {}~{}", symbol, start_str, end_str)
            return raw

        df = _canonical_columns(raw, symbol)
        # 规整 date 列为 ISO 字符串(SQLite 友好,排序也对)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df.insert(0, "symbol", symbol)
        # 数值列强制浮点
        for col in ("open", "high", "low", "close", "volume", "amount"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"])
        if route == "eastmoney":
            # Eastmoney reports A-share volume in lots (手); canonical storage uses shares.
            df["volume"] = df["volume"] * 100.0

        if self.persist:
            self._storage().save_bars_with_lineage(
                df,
                source_type="akshare_api",
                source_reference=route,
                source_metadata={"adjust_requested": self.adjust, "provider_route": route},
            )
        self.fetch_routes[symbol] = route
        action = "Stored" if self.persist else "Fetched"
        logger.info("{} {} rows for {} via {}", action, len(df), symbol, route)
        return df

    def _fetch_raw(
        self,
        symbol: str,
        start_str: str,
        end_str: str,
    ) -> tuple[pd.DataFrame, str]:
        primary_error = ""
        try:
            primary = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_str,
                end_date=end_str,
                adjust=self.adjust,
            )
            if not primary.empty:
                return primary, "eastmoney"
            primary_error = "empty bars"
        except Exception as exc:  # noqa: BLE001 - preserve failure before fallback.
            primary_error = f"{type(exc).__name__}: {exc}"

        logger.warning(
            "Eastmoney bars unavailable for {} ({}); trying Sina fallback.",
            symbol,
            primary_error,
        )
        try:
            fallback = ak.stock_zh_a_daily(
                symbol=_sina_symbol(symbol),
                start_date=start_str,
                end_date=end_str,
                adjust=self.adjust,
            )
        except Exception as exc:  # noqa: BLE001 - raise combined provider evidence.
            raise RuntimeError(
                f"Eastmoney failed ({primary_error}); Sina failed ({type(exc).__name__}: {exc})"
            ) from exc
        if fallback.empty:
            raise RuntimeError(f"Eastmoney failed ({primary_error}); Sina returned empty bars")
        return fallback, "sina"

    def ensure_cached(
        self,
        symbol: str,
        start: str | date,
        end: str | date,
    ) -> None:
        """Make sure cache covers [start, end]; fetch incrementally if not.

        Network failures are logged as warnings but never raised — backtests
        should still be runnable from whatever data is already cached.
        """
        storage = self._storage()
        last = storage.last_date(symbol)
        end_str = _to_iso(end)
        if last is not None and last >= end_str:
            logger.debug("Cache hit for {} up to {}", symbol, last)
            return
        # 增量拉取:从上次缓存末尾+1 拉到 end
        fetch_start = start
        if last is not None:
            fetch_start = (datetime.fromisoformat(last) + timedelta(days=1)).date()
        try:
            self.fetch(symbol, fetch_start, end)
        except Exception as exc:
            logger.warning(
                "Incremental fetch failed for {} ({} → {}): {}. "
                "Falling back to cached data.",
                symbol, fetch_start, end_str, exc,
            )

    def stream(
        self,
        symbols: list[str],
        start: str | date,
        end: str | date,
    ) -> Iterator[Bar]:
        """Merge bars across symbols, yield in chronological order.

        For daily data this is simple: load each symbol from cache, concat, sort.
        For minute/tick we'd need a heap-merge — out of scope for MVP.
        """
        frames: list[pd.DataFrame] = []
        for sym in symbols:
            self.ensure_cached(sym, start, end)
            frames.append(self._storage().load_bars(sym, start, end))
        if not frames:
            return
        merged = pd.concat(frames, ignore_index=True).sort_values(["date", "symbol"])
        for row in merged.itertuples(index=False):
            yield Bar(
                symbol=row.symbol,
                timestamp=datetime.fromisoformat(row.date),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
                amount=float(row.amount),
            )

    def _storage(self) -> BarStorage:
        if self.storage is None:
            raise RuntimeError("cache operations require a BarStorage instance")
        return self.storage


def _to_akshare_date(d: str | date) -> str:
    """AKShare wants 'YYYYMMDD' format."""
    if isinstance(d, str):
        return d.replace("-", "")
    return d.strftime("%Y%m%d")


def _to_iso(d: str | date) -> str:
    if isinstance(d, str):
        return d
    return d.isoformat()


def _canonical_columns(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    renamed = raw.rename(columns=_COLUMN_MAP)
    required = list(_COLUMN_MAP.values())
    missing = [column for column in required if column not in renamed]
    if missing:
        raise ValueError(f"AKShare bars for {symbol} are missing columns: {', '.join(missing)}")
    return renamed[required].copy()


def _sina_symbol(symbol: str) -> str:
    clean = str(symbol).strip().zfill(6)
    if clean.startswith(("4", "8")):
        return f"bj{clean}"
    if clean.startswith(("5", "6", "9")):
        return f"sh{clean}"
    return f"sz{clean}"
