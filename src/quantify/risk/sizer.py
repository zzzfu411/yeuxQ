"""Position sizers: turn an unsized SignalEvent into a sized OrderEvent quantity.

A signal says *what direction* to trade. A sizer says *how many shares*.

The split lets you swap sizing logic (fixed cash, fixed %, Kelly, volatility-
target, etc.) without touching strategies.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from quantify.core.portfolio import Portfolio


class Sizer(ABC):
    @abstractmethod
    def size(
        self,
        symbol: str,
        ref_price: float,
        portfolio: Portfolio,
    ) -> int:
        """Return the (positive) share quantity for opening a long position.

        ref_price is the most recent close (used to estimate share count).
        Implementations should round to 100-share lots for A-share.
        """


class FixedPctSizer(Sizer):
    """Spend a fixed % of *current total equity* on each new long.

    Total equity = cash + market value of all positions.
    """

    def __init__(self, pct: float = 0.2, lot_size: int = 100) -> None:
        if not 0 < pct <= 1.0:
            raise ValueError(f"pct must be in (0, 1], got {pct}")
        self.pct = pct
        self.lot_size = lot_size

    def size(self, symbol: str, ref_price: float, portfolio: Portfolio) -> int:
        # 用现金做上限,避免出现保证金不足
        # 总净值用于决定理论目标头寸,但实际下单不能超过现金
        total_equity = portfolio.cash  # MVP: 暂以现金为准,严格保守
        target_cash = total_equity * self.pct
        raw_qty = int(target_cash // ref_price)
        # 规整到 100 股整数倍
        qty = (raw_qty // self.lot_size) * self.lot_size
        return max(qty, 0)


class FixedCashSizer(Sizer):
    """Spend a fixed cash amount per trade."""

    def __init__(self, cash: float, lot_size: int = 100) -> None:
        if cash <= 0:
            raise ValueError("cash must be positive")
        self.cash = cash
        self.lot_size = lot_size

    def size(self, symbol: str, ref_price: float, portfolio: Portfolio) -> int:
        budget = min(self.cash, portfolio.cash)
        raw_qty = int(budget // ref_price)
        qty = (raw_qty // self.lot_size) * self.lot_size
        return max(qty, 0)
