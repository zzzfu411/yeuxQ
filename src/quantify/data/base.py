"""DataFeed: abstract source of historical bars.

Adapter pattern: A-share (akshare), US stocks (yfinance), crypto (ccxt) each
implement this interface so the rest of the system stays market-agnostic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import date

import pandas as pd

from quantify.core.bar import Bar


class DataFeed(ABC):
    """Read historical OHLCV bars for one or more symbols.

    Implementations are responsible for:
      - converting market-specific schemas to the canonical columns
        (symbol/date/open/high/low/close/volume/amount)
      - persisting to local cache so backtests don't re-download
    """

    @abstractmethod
    def fetch(
        self,
        symbol: str,
        start: str | date,
        end: str | date,
    ) -> pd.DataFrame:
        """Pull raw history from the upstream provider into the local cache."""

    @abstractmethod
    def stream(
        self,
        symbols: list[str],
        start: str | date,
        end: str | date,
    ) -> Iterator[Bar]:
        """Yield bars in chronological order, merged across symbols.

        Used by the backtest event loop. Each yielded Bar becomes a MarketEvent.
        """
