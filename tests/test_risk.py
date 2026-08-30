"""Tests for risk/sizer modules."""
from __future__ import annotations

from datetime import datetime

from quantify.core.event import Direction, FillEvent, SignalEvent
from quantify.core.portfolio import Portfolio, Position
from quantify.risk.manager import RiskConfig, RiskManager
from quantify.risk.sizer import FixedCashSizer, FixedPctSizer


def make_portfolio(cash: float = 100_000.0) -> Portfolio:
    return Portfolio(initial_cash=cash)


# ----- Sizer -----

def test_fixed_pct_sizer_rounds_to_lots() -> None:
    """20% of 100000 cash @ price 73 → 273 shares → rounded to 200."""
    pf = make_portfolio(100_000.0)
    sizer = FixedPctSizer(pct=0.2, lot_size=100)
    qty = sizer.size("X", ref_price=73.0, portfolio=pf)
    # 20000 / 73 ≈ 273 → floor to 100s → 200
    assert qty == 200


def test_fixed_pct_sizer_zero_when_too_small() -> None:
    pf = make_portfolio(50.0)  # 不够买 1 手
    sizer = FixedPctSizer(pct=0.5, lot_size=100)
    assert sizer.size("X", ref_price=10.0, portfolio=pf) == 0


def test_fixed_cash_sizer_capped_by_cash() -> None:
    pf = make_portfolio(500.0)
    sizer = FixedCashSizer(cash=10_000.0, lot_size=100)
    # Budget = min(10000, 500) = 500. At price 4 → 125 shares → 100
    qty = sizer.size("X", ref_price=4.0, portfolio=pf)
    assert qty == 100


# ----- RiskManager -----

def test_risk_long_signal_produces_order() -> None:
    pf = make_portfolio(100_000.0)
    rm = RiskManager(RiskConfig(max_position_pct=1.0), FixedPctSizer(pct=0.5))
    sig = SignalEvent(datetime(2024, 1, 2), "X", Direction.LONG)
    order = rm.process(sig, pf, ref_price=100.0)
    assert order is not None
    assert order.direction == Direction.LONG
    # 50% of 100k @ 100 = 500 shares (already a lot multiple)
    assert order.quantity == 500


def test_risk_exit_uses_available_only() -> None:
    """EXIT must size to available_qty (T+1-safe), not total_qty."""
    pf = make_portfolio(100_000.0)
    pf.on_new_day(datetime(2024, 1, 2).date())
    pf.apply_fill(FillEvent(datetime(2024, 1, 2), "X", Direction.LONG, 100, 100.0, 5.0))
    pf.on_new_day(datetime(2024, 1, 3).date())  # release T+1
    pf.apply_fill(FillEvent(datetime(2024, 1, 3), "X", Direction.LONG, 100, 100.0, 5.0))
    # available = 100 (day-1 buy), bought_today = 100 (day-3 buy)
    assert pf.positions["X"].available_qty == 100
    assert pf.positions["X"].total_qty == 200

    rm = RiskManager(RiskConfig(), FixedPctSizer())
    order = rm.process(
        SignalEvent(datetime(2024, 1, 3), "X", Direction.EXIT), pf, ref_price=100.0
    )
    assert order is not None
    assert order.quantity == 100  # only the T+1-released portion


def test_risk_exit_no_position_returns_none() -> None:
    pf = make_portfolio(100_000.0)
    rm = RiskManager(RiskConfig(), FixedPctSizer())
    order = rm.process(
        SignalEvent(datetime(2024, 1, 2), "X", Direction.EXIT), pf, ref_price=100.0
    )
    assert order is None


def test_risk_dd_breaker_blocks_new_longs() -> None:
    pf = make_portfolio(100_000.0)
    rm = RiskManager(
        RiskConfig(max_drawdown_stop=0.10, max_position_pct=1.0),
        FixedPctSizer(pct=0.5),
    )
    # 模拟净值峰值 100000,然后跌到 89000 (-11%) → 触发
    rm.update_equity(100_000)
    rm.update_equity(89_000)

    sig = SignalEvent(datetime(2024, 1, 2), "X", Direction.LONG)
    assert rm.process(sig, pf, ref_price=100.0) is None


def test_risk_position_cap_truncates_quantity() -> None:
    """Sizer asks for 800 shares (80%) but max_position_pct=0.3 → cap at 300."""
    pf = make_portfolio(100_000.0)
    rm = RiskManager(
        RiskConfig(max_position_pct=0.3),
        FixedPctSizer(pct=0.8),
    )
    sig = SignalEvent(datetime(2024, 1, 2), "X", Direction.LONG)
    order = rm.process(sig, pf, ref_price=100.0)
    assert order is not None
    # 0.3 * 100000 = 30000 → 30000/100 = 300 shares
    assert order.quantity == 300


def test_risk_position_cap_uses_each_holding_market_price() -> None:
    pf = make_portfolio(10_000.0)
    pf.positions["A"] = Position(
        symbol="A",
        total_qty=100,
        available_qty=100,
        avg_cost=100.0,
    )
    rm = RiskManager(
        RiskConfig(max_position_pct=0.3),
        FixedPctSizer(pct=1.0),
    )

    order = rm.process(
        SignalEvent(datetime(2024, 1, 2), "B", Direction.LONG),
        pf,
        ref_price=10.0,
        prices={"A": 100.0, "B": 10.0},
    )

    assert order is not None
    assert order.quantity == 600
