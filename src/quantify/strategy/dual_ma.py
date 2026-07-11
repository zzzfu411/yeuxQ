"""Dual-MA crossover strategy: the canonical 'hello world' of quantitative trading.

Rules:
    - When short MA crosses above long MA → LONG (buy)
    - When short MA crosses below long MA → EXIT (sell all)

We track an in-memory ring buffer of recent closes per symbol so we can compute
the moving averages incrementally without re-scanning the full history each bar.

Notes on look-ahead:
    The signal is generated using `close` of the *current* bar, but the broker
    will fill at the *next* bar's open. This is the correct, non-cheating pattern
    — see engine/broker_sim.py.
"""
from __future__ import annotations

from collections import deque
from typing import Iterable

from quantify.core.bar import Bar
from quantify.core.event import Direction, SignalEvent
from quantify.strategy.base import Strategy


class DualMAStrategy(Strategy):
    """Long when short MA > long MA, exit when reverse.

    Args:
        short_window: short MA period in bars (default 5)
        long_window:  long MA period in bars (default 20)
        universe:     list of symbols to trade
    """

    name = "DualMA"

    def __init__(
        self,
        short_window: int = 5,
        long_window: int = 20,
        universe: Iterable[str] = (),
    ) -> None:
        super().__init__(
            short_window=short_window,
            long_window=long_window,
            universe=list(universe),
        )
        if short_window >= long_window:
            raise ValueError(f"short_window ({short_window}) must be < long_window ({long_window})")
        self.short = short_window
        self.long = long_window
        self.universe = set(universe)
        # 每标的一个收盘价环形缓冲;长度只需保留 long 期(再多无用)
        self._closes: dict[str, deque[float]] = {}
        # 持仓状态:True=当前持有多头,False=空仓
        # 用于检测"穿越",避免在已持仓时重复发送 LONG 信号
        self._long_held: dict[str, bool] = {}

    def on_init(self) -> None:
        for sym in self.universe:
            self._closes[sym] = deque(maxlen=self.long)
            self._long_held[sym] = False

    def on_bar(self, bar: Bar) -> list[SignalEvent]:
        if bar.symbol not in self.universe:
            return []

        buf = self._closes[bar.symbol]
        buf.append(bar.close)
        # 必须先攒够 long 个数据点才能算长 MA
        if len(buf) < self.long:
            return []

        closes = list(buf)
        ma_short = sum(closes[-self.short:]) / self.short
        ma_long = sum(closes) / self.long

        # 上次的状态(用于检测金叉/死叉)。我们用持仓 flag 当 proxy:
        # 没持有 + 短上穿长 → 金叉买入
        # 持有 + 短下穿长   → 死叉卖出
        holding = self._long_held[bar.symbol]
        signals: list[SignalEvent] = []

        if not holding and ma_short > ma_long:
            signals.append(SignalEvent(
                timestamp=bar.timestamp,
                symbol=bar.symbol,
                direction=Direction.LONG,
            ))
            self._long_held[bar.symbol] = True
        elif holding and ma_short < ma_long:
            signals.append(SignalEvent(
                timestamp=bar.timestamp,
                symbol=bar.symbol,
                direction=Direction.EXIT,
            ))
            self._long_held[bar.symbol] = False

        return signals
