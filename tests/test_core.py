"""Tests for core data structures: Bar, events, Portfolio."""
from __future__ import annotations

from datetime import datetime

import pytest

from quantify.core.bar import Bar
from quantify.core.event import (
    Direction,
    EventType,
    FillEvent,
    MarketEvent,
    OrderEvent,
    OrderType,
    SignalEvent,
)
from quantify.core.portfolio import Portfolio


# ----- Bar -----

def test_bar_basic() -> None:
    bar = Bar(
        symbol="600519",
        timestamp=datetime(2024, 1, 2),
        open=1700.0,
        high=1720.0,
        low=1690.0,
        close=1710.0,
        volume=10000,
        amount=17_000_000.0,
    )
    assert bar.symbol == "600519"
    assert bar.close == 1710.0


def test_bar_invariant_violation() -> None:
    # low > open should raise
    with pytest.raises(ValueError, match="invariant"):
        Bar(
            symbol="X",
            timestamp=datetime(2024, 1, 2),
            open=100.0,
            high=110.0,
            low=105.0,  # > open
            close=108.0,
            volume=1,
        )


# ----- Events -----

def test_market_event_carries_bar() -> None:
    bar = Bar("X", datetime(2024, 1, 2), 100, 110, 95, 105, 1000)
    ev = MarketEvent(bar)
    assert ev.type == EventType.MARKET
    assert ev.bar.close == 105
    assert ev.timestamp == bar.timestamp


def test_signal_and_order_event() -> None:
    ts = datetime(2024, 1, 2)
    sig = SignalEvent(ts, "X", Direction.LONG)
    assert sig.type == EventType.SIGNAL
    assert sig.strength == 1.0

    order = OrderEvent(ts, "X", Direction.LONG, 200)
    assert order.type == EventType.ORDER
    assert order.order_type == OrderType.MARKET
    assert order.quantity == 200


def test_fill_event_cost_computation() -> None:
    fill = FillEvent(
        timestamp=datetime(2024, 1, 2),
        symbol="X",
        direction=Direction.LONG,
        quantity=100,
        fill_price=10.0,
        commission=5.0,
        tax=0.0,
    )
    assert fill.gross_value == 1000.0
    assert fill.total_cost == 1005.0


# ----- Portfolio -----

def test_portfolio_buy_updates_cash_and_position() -> None:
    pf = Portfolio(initial_cash=100_000.0)
    pf.on_new_day(datetime(2024, 1, 2).date())

    fill = FillEvent(
        timestamp=datetime(2024, 1, 2),
        symbol="600519",
        direction=Direction.LONG,
        quantity=100,
        fill_price=1700.0,
        commission=5.0,
        tax=0.0,
    )
    pf.apply_fill(fill)

    assert pf.cash == pytest.approx(100_000 - 170_000 - 5)
    pos = pf.positions["600519"]
    assert pos.total_qty == 100
    assert pos.available_qty == 0  # T+1: just bought today, not yet available
    assert pos.bought_today == 100
    assert pos.avg_cost == pytest.approx(1700.0)


def test_portfolio_t_plus_1_release() -> None:
    """T+1: day-1 buys become sellable on day-2."""
    pf = Portfolio(initial_cash=200_000.0)
    pf.on_new_day(datetime(2024, 1, 2).date())
    pf.apply_fill(
        FillEvent(datetime(2024, 1, 2), "X", Direction.LONG, 100, 100.0, 5.0)
    )
    assert pf.positions["X"].available_qty == 0  # T-day cannot sell

    pf.on_new_day(datetime(2024, 1, 3).date())  # new day → release
    assert pf.positions["X"].available_qty == 100


def test_portfolio_sell_blocked_when_only_bought_today() -> None:
    pf = Portfolio(initial_cash=100_000.0)
    pf.on_new_day(datetime(2024, 1, 2).date())
    pf.apply_fill(
        FillEvent(datetime(2024, 1, 2), "X", Direction.LONG, 100, 50.0, 5.0)
    )
    with pytest.raises(ValueError, match="T\\+1"):
        pf.apply_fill(
            FillEvent(datetime(2024, 1, 2), "X", Direction.EXIT, 100, 51.0, 5.0, tax=2.5)
        )


def test_portfolio_sell_after_release_updates_cash() -> None:
    pf = Portfolio(initial_cash=100_000.0)
    pf.on_new_day(datetime(2024, 1, 2).date())
    pf.apply_fill(
        FillEvent(datetime(2024, 1, 2), "X", Direction.LONG, 100, 50.0, commission=5.0)
    )
    pf.on_new_day(datetime(2024, 1, 3).date())
    pf.apply_fill(
        FillEvent(datetime(2024, 1, 3), "X", Direction.EXIT, 100, 55.0, commission=5.0, tax=2.75)
    )
    # cash = 100000 - 5005 (buy) + 5500 - 5 - 2.75 (sell)
    assert pf.cash == pytest.approx(100_000 - 5005 + 5500 - 5 - 2.75)
    assert pf.positions["X"].total_qty == 0


def test_portfolio_total_equity() -> None:
    pf = Portfolio(initial_cash=100_000.0)
    pf.on_new_day(datetime(2024, 1, 2).date())
    pf.apply_fill(
        FillEvent(datetime(2024, 1, 2), "X", Direction.LONG, 100, 100.0, commission=5.0)
    )
    # Cash left: 100000 - 10000 - 5 = 89995; position MV at 110 = 11000
    assert pf.total_equity({"X": 110.0}) == pytest.approx(89995 + 11000)


def test_portfolio_avg_cost_weighted() -> None:
    pf = Portfolio(initial_cash=1_000_000.0)
    pf.on_new_day(datetime(2024, 1, 2).date())
    pf.apply_fill(
        FillEvent(datetime(2024, 1, 2), "X", Direction.LONG, 100, 100.0, 5.0)
    )
    pf.apply_fill(
        FillEvent(datetime(2024, 1, 2), "X", Direction.LONG, 100, 120.0, 5.0)
    )
    # avg cost = (100*100 + 100*120) / 200 = 110
    assert pf.positions["X"].avg_cost == pytest.approx(110.0)
    assert pf.positions["X"].total_qty == 200
