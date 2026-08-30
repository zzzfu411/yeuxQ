"""数据源抽象与公共工具。"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Protocol

from yeuxq.domain.models import FundFlow, Kline, MinuteData, MinuteFlow, Quote

log = logging.getLogger("yeuxq.providers")

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
]


class RateLimiter:
    """简单令牌桶限速。"""

    def __init__(self, rate_per_second: float) -> None:
        self.rate = max(0.1, rate_per_second)
        self._tokens = self.rate
        self._last = time.monotonic()
        self._lock = threading.Lock()
        self.last_wait_seconds = 0.0

    def acquire(self) -> float:
        """Acquire one token and return the wait imposed by this call."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._last = now
            self._tokens = min(self.rate, self._tokens + elapsed * self.rate)
            if self._tokens < 1:
                need = (1 - self._tokens) / self.rate
                time.sleep(need)
                self._tokens = 0
                self.last_wait_seconds = need
            else:
                self._tokens -= 1
                self.last_wait_seconds = 0.0
            return self.last_wait_seconds


def to_float(v: Any) -> Optional[float]:
    if v is None or v == "-" or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def is_etf(symbol: str) -> bool:
    s = symbol.strip()
    return s.startswith(("5", "1")) and len(s) == 6


def symbol_to_secid(symbol: str) -> str:
    s = symbol.strip()
    if s.startswith(("6", "5", "9")):
        return f"1.{s}"
    if s.startswith("920"):
        return f"0.{s}"
    return f"0.{s}"


def symbol_to_tencent(symbol: str) -> str:
    s = symbol.strip()
    if s.startswith(("6", "5", "9")):
        return f"sh{s}"
    if s.startswith("920"):
        return f"bj{s}"
    return f"sz{s}"


def sina_symbol(symbol: str) -> str:
    s = symbol.strip()
    if s.startswith(("6", "5")):
        return f"sh{s}"
    if s.startswith("920"):
        return f"bj{s}"
    return f"sz{s}"


class MarketDataProvider(Protocol):
    def fetch_kline(self, symbol: str, count: int = 250, period: str = "day") -> List[Kline]: ...

    def fetch_quote(self, symbol: str) -> Optional[Quote]: ...

    def fetch_fund_flow(self, symbol: str, days: int = 30) -> List[FundFlow]: ...

    def fetch_realtime_flow(self, symbol: str) -> List[MinuteFlow]: ...

    def fetch_minute(self, symbol: str) -> Optional[MinuteData]: ...

    def search_stock(self, keyword: str, count: int = 10) -> List[Dict[str, str]]: ...

    def fetch_index_kline(self, index_code: str = "000001", count: int = 60) -> List[Kline]: ...

    def fetch_market_breadth(self) -> Optional[dict]: ...

    def fetch_symbols(self, limit: int = 200) -> List[Dict[str, str]]: ...


class OrderFlowProvider(ABC):
    """L2/盘口预留空接口（本期不实现）。"""

    @abstractmethod
    def fetch_order_book(self, symbol: str) -> Optional[dict]:
        raise NotImplementedError("Order book / L2 not available in free public feeds")

    @abstractmethod
    def fetch_tick_trades(self, symbol: str) -> List[dict]:
        raise NotImplementedError("Tick trades not available in free public feeds")
