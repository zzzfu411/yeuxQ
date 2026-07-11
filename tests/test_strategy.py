"""Tests for the dual-MA strategy with hand-crafted bar sequences."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from quantify.core.bar import Bar
from quantify.core.event import Direction
from quantify.strategy.dual_ma import DualMAStrategy


def make_bars(symbol: str, closes: list[float], start_day: int = 1) -> list[Bar]:
    """Build minimal Bars from a list of closing prices (1 bar/day)."""
    return [
        Bar(
            symbol=symbol,
            timestamp=datetime(2024, 1, 1) + timedelta(days=i + start_day - 1),
            open=c,
            high=c,
            low=c,
            close=c,
            volume=1.0,
        )
        for i, c in enumerate(closes)
    ]


def test_dual_ma_warmup_no_signal() -> None:
    """Before long_window bars accumulate, no signals."""
    strat = DualMAStrategy(short_window=2, long_window=4, universe=["X"])
    strat.on_init()
    bars = make_bars("X", [1, 2, 3])
    out = []
    for b in bars:
        out.extend(strat.on_bar(b))
    assert out == []


def test_dual_ma_golden_cross_buys() -> None:
    """A clear short>long crossover should produce one LONG signal."""
    strat = DualMAStrategy(short_window=2, long_window=4, universe=["X"])
    strat.on_init()
    # First 4 bars: strictly decreasing → short MA below long MA, no signal
    # Then upward swing → short MA crosses above long MA → LONG
    closes = [10, 9, 8, 7, 8, 11, 14]
    signals = []
    for b in make_bars("X", closes):
        signals.extend(strat.on_bar(b))

    assert len(signals) == 1, f"expected 1 LONG signal, got {signals}"
    assert signals[0].direction == Direction.LONG


def test_dual_ma_death_cross_exits() -> None:
    """After a buy, a downward crossover should produce one EXIT signal."""
    strat = DualMAStrategy(short_window=2, long_window=4, universe=["X"])
    strat.on_init()
    # Up then down
    closes = [1, 2, 3, 4, 6, 8, 10, 9, 5, 2, 1]
    signals = []
    for b in make_bars("X", closes):
        signals.extend(strat.on_bar(b))

    directions = [s.direction for s in signals]
    assert Direction.LONG in directions
    assert Direction.EXIT in directions
    # LONG must come before EXIT
    assert directions.index(Direction.LONG) < directions.index(Direction.EXIT)


def test_dual_ma_no_double_buy() -> None:
    """While already long, additional positive crossover-ish bars should NOT
    re-emit LONG."""
    strat = DualMAStrategy(short_window=2, long_window=4, universe=["X"])
    strat.on_init()
    closes = [1, 2, 3, 4, 6, 8, 10, 12, 14]  # always trending up after warmup
    signals = []
    for b in make_bars("X", closes):
        signals.extend(strat.on_bar(b))
    # Only one LONG, no further signals while already holding
    longs = [s for s in signals if s.direction == Direction.LONG]
    assert len(longs) == 1


def test_dual_ma_ignores_off_universe_symbol() -> None:
    strat = DualMAStrategy(short_window=2, long_window=4, universe=["X"])
    strat.on_init()
    bars = make_bars("Y", [1, 2, 3, 4, 5, 6])
    out = []
    for b in bars:
        out.extend(strat.on_bar(b))
    assert out == []


def test_dual_ma_invalid_window() -> None:
    with pytest.raises(ValueError, match="must be"):
        DualMAStrategy(short_window=10, long_window=10, universe=["X"])
