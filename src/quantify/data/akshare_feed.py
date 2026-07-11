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

    def __init__(self, storage: BarStorage, adjust: str = "qfq") -> None:
        """
        Args:
            storage: BarStorage instance for cache.
            adjust:  '' / 'qfq' / 'hfq' — 不复权 / 前复权 / 后复权.
                     Default 前复权(qfq):适合多数策略回测,避免分红送股导致价格跳变。
        """
        self.storage = storage
        if adjust not in ("", "qfq", "hfq"):
            raise ValueError(f"adjust must be '', 'qfq' or 'hfq', got {adjust!r}")
        self.adjust = adjust

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
        raw = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_str,
            end_date=end_str,
            adjust=self.adjust,
        )
        if raw.empty:
            logger.warning("AKShare returned 0 rows for {} {}~{}", symbol, start_str, end_str)
            return raw

        df = raw.rename(columns=_COLUMN_MAP)[list(_COLUMN_MAP.values())].copy()
        # 规整 date 列为 ISO 字符串(SQLite 友好,排序也对)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df.insert(0, "symbol", symbol)
        # 数值列强制浮点
        for col in ("open", "high", "low", "close", "volume", "amount"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"])

        self.storage.save_bars(df)
        logger.info("Stored {} rows for {}", len(df), symbol)
        return df

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
        last = self.storage.last_date(symbol)
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
            frames.append(self.storage.load_bars(sym, start, end))
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


def _to_akshare_date(d: str | date) -> str:
    """AKShare wants 'YYYYMMDD' format."""
    if isinstance(d, str):
        return d.replace("-", "")
    return d.strftime("%Y%m%d")


def _to_iso(d: str | date) -> str:
    if isinstance(d, str):
        return d
    return d.isoformat()
