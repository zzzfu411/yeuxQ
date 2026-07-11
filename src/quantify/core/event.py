"""Events: the only thing that flows through the system.

The four event types correspond one-to-one with the arrows in the architecture diagram:
    MARKET → SIGNAL → ORDER → FILL

Keeping all communication as events lets us swap BrokerSim ↔ LiveBroker without
touching strategies, and lets the same backtest engine drive a paper-trading loop.

We deliberately use independent dataclasses (no inheritance) rather than a base
Event class — dataclass + slots + inheritance interacts badly, and flat classes
are easier to read.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Union

from quantify.core.bar import Bar


class EventType(str, Enum):
    MARKET = "MARKET"
    SIGNAL = "SIGNAL"
    ORDER = "ORDER"
    FILL = "FILL"


class Direction(str, Enum):
    LONG = "LONG"    # 买入开仓 / 增仓
    SHORT = "SHORT"  # 卖出平仓(MVP 不做做空,SHORT 仅作语义)
    EXIT = "EXIT"    # 平所有该标的仓位


class OrderType(str, Enum):
    MARKET = "MARKET"  # 市价单(MVP 默认):用下一根 bar 的开盘价成交
    LIMIT = "LIMIT"    # 限价单(MVP 不实现,留接口)


@dataclass(slots=True, frozen=True)
class MarketEvent:
    """新一根 K 线到达,驱动整个流水线的源头事件。"""
    bar: Bar

    @property
    def type(self) -> EventType:
        return EventType.MARKET

    @property
    def timestamp(self) -> datetime:
        return self.bar.timestamp


@dataclass(slots=True, frozen=True)
class SignalEvent:
    """策略对某标的的买卖建议,不含数量(数量由 risk/sizer 决定)。

    strength 表示信号强度(0~1),可被 Kelly 等头寸计算器使用,默认 1.0。
    """
    timestamp: datetime
    symbol: str
    direction: Direction
    strength: float = 1.0

    @property
    def type(self) -> EventType:
        return EventType.SIGNAL


@dataclass(slots=True, frozen=True)
class OrderEvent:
    """风控/头寸计算后的实际订单,包含数量。

    A 股下单量必须是 100 股整数倍,由 sizer 负责规整。
    """
    timestamp: datetime
    symbol: str
    direction: Direction
    quantity: int
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None  # 仅 LIMIT 单使用

    @property
    def type(self) -> EventType:
        return EventType.ORDER


@dataclass(slots=True, frozen=True)
class FillEvent:
    """订单成交回报。fill_price 已包含滑点,commission/tax 已计算。"""
    timestamp: datetime
    symbol: str
    direction: Direction
    quantity: int
    fill_price: float
    commission: float = 0.0
    tax: float = 0.0  # 印花税(A 股仅卖出)

    @property
    def type(self) -> EventType:
        return EventType.FILL

    @property
    def gross_value(self) -> float:
        """成交金额(不含手续费),= 价 × 量。"""
        return self.fill_price * self.quantity

    @property
    def total_cost(self) -> float:
        """买入时的现金消耗(含费)。"""
        return self.gross_value + self.commission + self.tax


@dataclass(slots=True, frozen=True)
class PortfolioTarget:
    """Target portfolio weight for one symbol on a rebalance date.

    The research engine uses target weights instead of immediate buy/sell
    signals. A PaperBroker turns these weights into executable A-share orders.
    """

    timestamp: datetime
    symbol: str
    target_weight: float
    score: float = 0.0


# 便于类型注解的联合类型
Event = Union[MarketEvent, SignalEvent, OrderEvent, FillEvent]
