"""Research data facade.

DataProvider is the single read API used by factor research and paper trading.
It hides whether data came from AKShare, CSV fixtures, or hand-seeded SQLite
tables, keeping strategies away from network/provider details.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from quantify.data.storage import BarStorage


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    missing_bars: list[str]
    missing_fundamentals: list[str]
    notes: list[str]

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "missing_bars": self.missing_bars,
            "missing_fundamentals": self.missing_fundamentals,
            "notes": self.notes,
        }


class DataProvider:
    """Unified research data access over local SQLite cache."""

    def __init__(self, storage: BarStorage) -> None:
        self.storage = storage

    def trading_days(self, start: str | date, end: str | date) -> list[str]:
        days = self.storage.load_calendar(start, end)
        if days:
            return days
        bars = self.storage.load_all_bars(self.all_symbols(), start, end)
        if bars.empty:
            return []
        return sorted(bars["date"].unique().tolist())

    def all_symbols(self) -> list[str]:
        info = self.storage.load_stock_info()
        if not info.empty:
            return sorted(info["symbol"].astype(str).tolist())
        with_bars = self.storage.load_all_bars_from_db_symbols()
        return sorted(with_bars)

    def bars(
        self,
        symbols: list[str],
        start: str | date,
        end: str | date,
    ) -> pd.DataFrame:
        return self.storage.load_all_bars(symbols, start, end)

    def close_matrix(
        self,
        symbols: list[str],
        start: str | date,
        end: str | date,
    ) -> pd.DataFrame:
        bars = self.bars(symbols, start, end)
        if bars.empty:
            return pd.DataFrame()
        matrix = bars.pivot(index="date", columns="symbol", values="close").sort_index()
        return matrix.ffill()

    def latest_prices(self, symbols: list[str], as_of: str | date) -> dict[str, float]:
        bars = self.storage.load_all_bars(symbols, end=as_of)
        if bars.empty:
            return {}
        latest = bars.sort_values(["symbol", "date"]).groupby("symbol").tail(1)
        return dict(zip(latest["symbol"], latest["close"], strict=False))

    def open_prices(self, symbols: list[str], as_of: str | date) -> dict[str, float]:
        """Return exact-day opening prices without carrying stale bars forward."""
        bars = self.storage.load_all_bars(symbols, start=as_of, end=as_of)
        if bars.empty:
            return {}
        return dict(zip(bars["symbol"], bars["open"], strict=False))

    def fundamentals(self, symbols: list[str], as_of: str | date) -> pd.DataFrame:
        return self.storage.load_fundamentals(symbols, as_of)

    def stock_info(self) -> pd.DataFrame:
        return self.storage.load_stock_info()

    def metadata(self) -> dict[str, str]:
        return self.storage.load_metadata()

    def index_constituents(self, index_code: str, as_of: str | date) -> list[str]:
        return self.storage.load_index_constituents(index_code, as_of)

    def suspended_symbols(self, as_of: str | date) -> set[str]:
        return self.storage.load_suspended_symbols(as_of)

    def quality_report(self, symbols: list[str], as_of: str | date) -> DataQualityReport:
        prices = self.latest_prices(symbols, as_of)
        fundamentals = self.fundamentals(symbols, as_of)
        missing_bars = sorted(set(symbols) - set(prices))
        missing_fundamentals = sorted(set(symbols) - set(fundamentals["symbol"].astype(str)))
        notes = []
        if missing_bars:
            notes.append("Some symbols have no cached bars on or before the requested date.")
        if missing_fundamentals:
            notes.append("Some symbols have no cached fundamentals; valuation/quality scores may be neutral.")
        return DataQualityReport(missing_bars, missing_fundamentals, notes)
