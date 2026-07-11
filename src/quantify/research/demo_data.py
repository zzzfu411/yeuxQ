"""Deterministic demo dataset for first-run tutorials and tests."""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from quantify.data.storage import BarStorage


def seed_demo_data(storage: BarStorage, start: str = "2020-01-01", end: str = "2021-12-31") -> list[str]:
    """Seed a small synthetic A-share-like dataset when no real cache exists."""
    symbols = [f"DEMO{i:03d}" for i in range(1, 13)]
    dates = pd.bdate_range(start, end)
    storage.save_calendar(pd.DatetimeIndex(dates))
    info = pd.DataFrame(
        {
            "symbol": symbols,
            "name": [f"演示股票{i:03d}" for i in range(1, 13)],
            "exchange": ["SSE" if i % 2 else "SZSE" for i in range(1, 13)],
            "list_date": ["2010-01-01"] * len(symbols),
            "delist_date": [""] * len(symbols),
            "industry": ["科技", "消费", "医药", "制造"] * 3,
            "is_st": [0] * len(symbols),
        }
    )
    storage.save_stock_info(info)
    storage.save_index_constituents("000906", dates[0].date().isoformat(), symbols[:8])

    bar_frames = []
    fundamental_frames = []
    for idx, symbol in enumerate(symbols, start=1):
        rng = np.random.default_rng(idx)
        base = 8 + idx * 1.5
        drift = 0.0002 + idx * 0.00003
        noise = rng.normal(0, 0.012, len(dates))
        close = base * np.cumprod(1 + drift + noise)
        open_ = close * (1 + rng.normal(0, 0.003, len(dates)))
        high = np.maximum(open_, close) * 1.01
        low = np.minimum(open_, close) * 0.99
        volume = rng.integers(500_000, 3_000_000, len(dates))
        amount = volume * close
        bar_frames.append(
            pd.DataFrame(
                {
                    "symbol": symbol,
                    "date": [d.date().isoformat() for d in dates],
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "amount": amount,
                }
            )
        )

        quarter_dates = pd.date_range(start, end, freq="QE")
        if quarter_dates.empty:
            quarter_dates = pd.DatetimeIndex([datetime.fromisoformat(end)])
        fundamental_frames.append(
            pd.DataFrame(
                {
                    "symbol": symbol,
                    "date": [d.date().isoformat() for d in quarter_dates],
                    "pe_ttm": 8 + idx + rng.normal(0, 1.0, len(quarter_dates)),
                    "pb": 0.8 + idx * 0.08 + rng.normal(0, 0.05, len(quarter_dates)),
                    "roe": 0.06 + idx * 0.004 + rng.normal(0, 0.005, len(quarter_dates)),
                    "market_cap": 5e9 + idx * 8e8,
                    "turnover_rate": 1.0 + idx * 0.05,
                }
            )
        )

    storage.save_bars(pd.concat(bar_frames, ignore_index=True))
    storage.save_fundamentals(pd.concat(fundamental_frames, ignore_index=True))
    return symbols
