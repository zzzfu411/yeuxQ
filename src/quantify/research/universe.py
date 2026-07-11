"""Universe construction for A-share research."""
from __future__ import annotations

from dataclasses import dataclass

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

        info = data.stock_info()
        if not info.empty:
            info = info.set_index("symbol")

        suspended = data.suspended_symbols(as_of)
        prices = data.latest_prices(candidates, as_of)
        filtered: list[str] = []
        for symbol in candidates:
            if symbol in suspended or symbol not in prices:
                continue
            if not self.config.include_st and not info.empty:
                row = info.loc[symbol] if symbol in info.index else None
                if row is not None:
                    name = str(row.get("name", ""))
                    is_st = int(row.get("is_st", 0)) == 1
                    delist_date = str(row.get("delist_date", ""))
                    if is_st or "ST" in name.upper() or delist_date:
                        continue
            filtered.append(symbol)
        return sorted(filtered)
