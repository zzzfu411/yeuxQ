"""Paper broker that turns target weights into simulated A-share fills."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from quantify.core.event import Direction, FillEvent, PortfolioTarget
from quantify.core.portfolio import Portfolio


@dataclass(frozen=True, slots=True)
class PaperBrokerConfig:
    commission_rate: float = 0.00025
    min_commission: float = 5.0
    stamp_tax: float = 0.0005
    slippage_bps: float = 5.0
    lot_size: int = 100
    price_limit_pct: float = 0.10


@dataclass(frozen=True, slots=True)
class PaperOrder:
    timestamp: datetime
    symbol: str
    direction: Direction
    quantity: int
    price: float
    status: str
    reason: str = ""


@dataclass(slots=True)
class RebalanceResult:
    fills: list[FillEvent] = field(default_factory=list)
    orders: list[PaperOrder] = field(default_factory=list)
    turnover: float = 0.0


class PaperBroker:
    """A conservative paper-trading broker for daily A-share research."""

    def __init__(self, config: PaperBrokerConfig | None = None) -> None:
        self.config = config or PaperBrokerConfig()
        self.order_log: list[PaperOrder] = []

    def rebalance(
        self,
        targets: list[PortfolioTarget],
        prices: dict[str, float],
        portfolio: Portfolio,
        suspended: set[str] | None = None,
        prev_closes: dict[str, float] | None = None,
    ) -> RebalanceResult:
        suspended = suspended or set()
        prev_closes = prev_closes or {}
        timestamp = targets[0].timestamp if targets else datetime.now()
        target_weights = {target.symbol: max(target.target_weight, 0.0) for target in targets}
        symbols = sorted(set(target_weights) | set(portfolio.positions))
        equity = portfolio.total_equity(prices)
        result = RebalanceResult()

        # Sell first to free cash and respect T+1 availability.
        for symbol in symbols:
            pos = portfolio.positions.get(symbol)
            if pos is None or pos.total_qty <= 0:
                continue
            price = prices.get(symbol)
            if price is None:
                result.orders.append(PaperOrder(timestamp, symbol, Direction.EXIT, 0, 0.0, "rejected", "no_price"))
                continue
            if symbol in suspended or _limit_down(price, prev_closes.get(symbol), self.config.price_limit_pct):
                result.orders.append(PaperOrder(timestamp, symbol, Direction.EXIT, 0, price, "rejected", "not_sellable"))
                continue
            target_qty = int((equity * target_weights.get(symbol, 0.0)) // price)
            requested_sell_qty = max(pos.total_qty - target_qty, 0)
            sell_qty = min(requested_sell_qty, pos.available_qty)
            if sell_qty <= 0:
                if requested_sell_qty > 0:
                    result.orders.append(
                        PaperOrder(timestamp, symbol, Direction.EXIT, 0, price, "rejected", "t_plus_one")
                    )
                continue
            fill = self._make_fill(timestamp, symbol, Direction.EXIT, sell_qty, price)
            portfolio.apply_fill(fill)
            result.fills.append(fill)
            result.orders.append(PaperOrder(timestamp, symbol, Direction.EXIT, sell_qty, price, "filled"))
            result.turnover += fill.gross_value
            blocked_qty = requested_sell_qty - sell_qty
            if blocked_qty > 0:
                result.orders.append(
                    PaperOrder(timestamp, symbol, Direction.EXIT, blocked_qty, price, "rejected", "t_plus_one")
                )

        # Buy after sells; shrink each order to available cash and round lots.
        for target in targets:
            symbol = target.symbol
            price = prices.get(symbol)
            if price is None:
                result.orders.append(PaperOrder(target.timestamp, symbol, Direction.LONG, 0, 0.0, "rejected", "no_price"))
                continue
            if symbol in suspended or _limit_up(price, prev_closes.get(symbol), self.config.price_limit_pct):
                result.orders.append(PaperOrder(target.timestamp, symbol, Direction.LONG, 0, price, "rejected", "not_buyable"))
                continue
            pos = portfolio.positions.get(symbol)
            current_qty = pos.total_qty if pos else 0
            target_qty = int((equity * target.target_weight) // price)
            requested_buy_qty = max(target_qty - current_qty, 0)
            buy_qty = (requested_buy_qty // self.config.lot_size) * self.config.lot_size
            if buy_qty <= 0:
                if requested_buy_qty > 0:
                    result.orders.append(
                        PaperOrder(
                            target.timestamp,
                            symbol,
                            Direction.LONG,
                            requested_buy_qty,
                            price,
                            "rejected",
                            "below_lot",
                        )
                    )
                continue
            buy_qty = self._cap_by_cash(buy_qty, price, portfolio.cash)
            if buy_qty <= 0:
                result.orders.append(PaperOrder(target.timestamp, symbol, Direction.LONG, 0, price, "rejected", "cash"))
                continue
            fill = self._make_fill(target.timestamp, symbol, Direction.LONG, buy_qty, price)
            portfolio.apply_fill(fill)
            result.fills.append(fill)
            result.orders.append(PaperOrder(target.timestamp, symbol, Direction.LONG, buy_qty, price, "filled"))
            result.turnover += fill.gross_value

        self.order_log.extend(result.orders)
        return result

    def _make_fill(
        self,
        timestamp: datetime,
        symbol: str,
        direction: Direction,
        quantity: int,
        price: float,
    ) -> FillEvent:
        slip = self.config.slippage_bps / 10_000.0
        fill_price = price * (1 + slip) if direction == Direction.LONG else price * (1 - slip)
        fill_price = round(fill_price, 2)
        gross = fill_price * quantity
        commission = max(gross * self.config.commission_rate, self.config.min_commission)
        tax = gross * self.config.stamp_tax if direction != Direction.LONG else 0.0
        return FillEvent(
            timestamp=timestamp,
            symbol=symbol,
            direction=direction,
            quantity=quantity,
            fill_price=fill_price,
            commission=round(commission, 2),
            tax=round(tax, 2),
        )

    def _cap_by_cash(self, quantity: int, price: float, cash: float) -> int:
        qty = quantity
        while qty > 0:
            est_price = price * (1 + self.config.slippage_bps / 10_000.0)
            gross = est_price * qty
            commission = max(gross * self.config.commission_rate, self.config.min_commission)
            if gross + commission <= cash:
                return qty
            qty -= self.config.lot_size
        return 0


def _limit_up(price: float, prev_close: float | None, pct: float) -> bool:
    return prev_close is not None and price >= round(prev_close * (1 + pct), 2)


def _limit_down(price: float, prev_close: float | None, pct: float) -> bool:
    return prev_close is not None and price <= round(prev_close * (1 - pct), 2)
