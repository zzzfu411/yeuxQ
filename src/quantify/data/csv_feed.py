"""CSV feed: replay bars from a local CSV.

Useful for:
    - Tests: avoid hitting the network in unit tests.
    - Reproducibility: pin a known dataset to a known result.
    - Debugging: hand-craft edge-case data (limit-up days, gaps).

Expected CSV columns: symbol, date, open, high, low, close, volume, amount (optional).
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from quantify.core.bar import Bar
from quantify.data.base import DataFeed


class CsvFeed(DataFeed):
    """Load bars from a CSV file. No caching layer needed — the file IS the cache."""

    def __init__(self, csv_path: str | Path) -> None:
        self.csv_path = Path(csv_path)
        if not self.csv_path.exists():
            raise FileNotFoundError(self.csv_path)

    def _read(self) -> pd.DataFrame:
        df = pd.read_csv(self.csv_path)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        if "amount" not in df.columns:
            df["amount"] = 0.0
        return df

    def fetch(
        self,
        symbol: str,
        start: str | date,
        end: str | date,
    ) -> pd.DataFrame:
        df = self._read()
        df = df[df["symbol"] == symbol]
        start_iso = start if isinstance(start, str) else start.isoformat()
        end_iso = end if isinstance(end, str) else end.isoformat()
        return df[(df["date"] >= start_iso) & (df["date"] <= end_iso)].reset_index(drop=True)

    def stream(
        self,
        symbols: list[str],
        start: str | date,
        end: str | date,
    ) -> Iterator[Bar]:
        df = self._read()
        df = df[df["symbol"].isin(symbols)]
        start_iso = start if isinstance(start, str) else start.isoformat()
        end_iso = end if isinstance(end, str) else end.isoformat()
        df = df[(df["date"] >= start_iso) & (df["date"] <= end_iso)]
        df = df.sort_values(["date", "symbol"])
        for row in df.itertuples(index=False):
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
