"""Universe construction for A-share research."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from quantify.data.provider import DataProvider


@dataclass(frozen=True, slots=True)
class UniverseConfig:
    mode: str = "all_a"
    index_code: str = "000906"  # CSI 800 by common convention
    include_st: bool = False
    min_history_days: int = 120


class UniverseFilter:
    """Build a tradable stock universe with simple A-share hygiene filters."""

    def __init__(self, config: UniverseConfig) -> None:
        self.config = config

    def symbols(self, as_of: str, data: DataProvider) -> list[str]:
        if self.config.mode == "index":
            candidates = data.index_constituents(self.config.index_code, as_of)
        else:
            candidates = data.all_symbols()
        if not candidates:
            return []

        info = data.stock_info()
        if not info.empty:
            info = info.set_index("symbol")

        suspended = data.suspended_symbols(as_of)
        bars = data.bars(candidates, date.min, as_of)
        history_days = (
            bars.groupby("symbol")["date"].nunique() if not bars.empty else pd.Series(dtype="int64")
        )
        required_history_days = max(1, self.config.min_history_days)
        as_of_date = pd.to_datetime(as_of, errors="raise")
        filtered: list[str] = []
        for symbol in candidates:
            if symbol in suspended or history_days.get(symbol, 0) < required_history_days:
                continue
            if not info.empty:
                row = info.loc[symbol] if symbol in info.index else None
                if row is not None:
                    list_date = pd.to_datetime(row.get("list_date", ""), errors="coerce")
                    delist_date = pd.to_datetime(row.get("delist_date", ""), errors="coerce")
                    if pd.notna(list_date) and list_date > as_of_date:
                        continue
                    if pd.notna(delist_date) and delist_date <= as_of_date:
                        continue

                    name = str(row.get("name", ""))
                    is_st = int(row.get("is_st", 0)) == 1
                    if not self.config.include_st and (is_st or "ST" in name.upper()):
                        continue
            filtered.append(symbol)
        return sorted(filtered)
