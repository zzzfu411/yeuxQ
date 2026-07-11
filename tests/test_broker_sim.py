"""Tests for BrokerSim — A-share rules engine."""
from __future__ import annotations

from datetime import datetime

import pytest

from quantify.core.bar import Bar
from quantify.core.event import Direction, OrderEvent
from quantify.engine.broker_sim import BrokerConfig, BrokerSim


def _bar(symbol: str, day: int, open_: float, close: float) -> Bar:
    return Bar(symbol, datetime(2024, 1, day), open_, max(open_, close), min(open_, close), close, 1.0)


def test_buy_fills_at_next_open_with_slippage() -> None:
    cfg = BrokerConfig(commission_rate=0, min_commission=0, stamp_tax=0, slippage_bps=10)
    broker = BrokerSim(cfg)

    # Day 1: order submitted, no fill yet (no bar of that symbol after submit yet)
    order = OrderEvent(datetime(2024, 1, 1), "X", Direction.LONG, 100)
    broker.submit(order)
    fills = broker.on_bar(_bar("X", 2, open_=100.0, close=105.0))

    assert len(fills) == 1
    # 10 bps slippage on buy → 100 * 1.001 = 100.10
    assert fills[0].fill_price == pytest.approx(100.10)
    assert fills[0].direction == Direction.LONG


def test_sell_fills_with_negative_slippage_and_stamp_tax() -> None:
    cfg = BrokerConfig(commission_rate=0, min_commission=0, stamp_tax=0.001, slippage_bps=10)
    broker = BrokerSim(cfg)

    broker.submit(OrderEvent(datetime(2024, 1, 1), "X", Direction.EXIT, 100))
    fills = broker.on_bar(_bar("X", 2, open_=100.0, close=99.0))

    assert len(fills) == 1
    # Sell slippage adverse → 100 * 0.999 = 99.90
    assert fills[0].fill_price == pytest.approx(99.90)
    # Stamp tax = 99.90 * 100 * 0.001 = 9.99
    assert fills[0].tax == pytest.approx(9.99)


def test_commission_min_floor() -> None:
    """For tiny orders, commission rate × gross may be below the minimum."""
    cfg = BrokerConfig(commission_rate=0.0001, min_commission=5.0, stamp_tax=0, slippage_bps=0)
    broker = BrokerSim(cfg)
    broker.submit(OrderEvent(datetime(2024, 1, 1), "X", Direction.LONG, 100))
    fills = broker.on_bar(_bar("X", 2, open_=10.0, close=10.0))
    # Gross = 1000, fee@0.01% = 0.10, but min is 5
    assert fills[0].commission == pytest.approx(5.0)


def test_buy_round_lot_truncated() -> None:
    """Buying 250 shares should truncate to 200 (multiples of 100)."""
    broker = BrokerSim(BrokerConfig(slippage_bps=0, commission_rate=0, min_commission=0, stamp_tax=0))
    broker.submit(OrderEvent(datetime(2024, 1, 1), "X", Direction.LONG, 250))
    fills = broker.on_bar(_bar("X", 2, open_=10.0, close=10.0))
    assert fills[0].quantity == 200


def test_limit_up_blocks_buy() -> None:
    """When the next open already hit upper limit, buy orders are rejected."""
    broker = BrokerSim(BrokerConfig(price_limit_pct=0.10, slippage_bps=0))
    # Establish a prev_close=10 first
    broker.on_bar(_bar("X", 1, open_=10.0, close=10.0))
    # Submit buy; next bar opens at 11.0 = +10% = limit up → reject
    broker.submit(OrderEvent(datetime(2024, 1, 2), "X", Direction.LONG, 100))
    fills = broker.on_bar(_bar("X", 2, open_=11.0, close=11.0))
    assert fills == []


def test_limit_down_blocks_sell() -> None:
    broker = BrokerSim(BrokerConfig(price_limit_pct=0.10, slippage_bps=0))
    broker.on_bar(_bar("X", 1, open_=10.0, close=10.0))
    broker.submit(OrderEvent(datetime(2024, 1, 2), "X", Direction.EXIT, 100))
    fills = broker.on_bar(_bar("X", 2, open_=9.0, close=9.0))
    assert fills == []


def test_non_matching_symbol_keeps_order_pending() -> None:
    broker = BrokerSim(BrokerConfig(slippage_bps=0))
    broker.submit(OrderEvent(datetime(2024, 1, 1), "X", Direction.LONG, 100))
    # A bar for a different symbol does NOT consume the X order
    fills = broker.on_bar(_bar("Y", 2, 10.0, 10.0))
    assert fills == []
    assert broker.pending_count() == 1


def test_zero_quantity_ignored() -> None:
    broker = BrokerSim()
    broker.submit(OrderEvent(datetime(2024, 1, 1), "X", Direction.LONG, 0))
    assert broker.pending_count() == 0
