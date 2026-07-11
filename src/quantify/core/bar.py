"""Bar: a single OHLCV record for one symbol on one trading period.

The Bar is the atomic unit of market data. The whole system is built around it:
data feeds emit bars, strategies react to bars, brokers fill orders at the next bar.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    # 成交额(amount)在 A 股是常用字段,可与 volume 区分(volume=手数,amount=元)
    amount: float = 0.0

    def __post_init__(self) -> None:
        # 不变式:OHLC 必须满足 low <= open,close <= high
        # frozen dataclass 没法在 __init__ 之外断言,这里做事后校验
        if not (self.low <= self.open <= self.high):
            raise ValueError(f"Bar invariant violated: low<=open<=high failed for {self}")
        if not (self.low <= self.close <= self.high):
            raise ValueError(f"Bar invariant violated: low<=close<=high failed for {self}")
