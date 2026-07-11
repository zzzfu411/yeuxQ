"""Simulated broker for A-share daily backtests.

Encapsulates all A-share-specific rules so the rest of the engine stays generic:
    1. T+1: cannot sell shares bought on the same trading day (enforced in Portfolio).
    2. Price/volume limits (涨跌停): orders rejected if next bar's open hits limit.
    3. Round lots (整百股): buy quantities must be multiples of 100.
    4. Commission: 万分之 2.5,最低 5 元 (broker fee, both buy and sell).
    5. Stamp tax (印花税): 0.05% on sells only (post-2023 rate).
    6. Slippage: simulated as +/- N basis points around fill price.

Fill model:
    A market order arriving on bar N fills at bar N+1's open price,
    adjusted by slippage. This is the *non-cheating* model: when a strategy
    sees bar N's close, it could not have traded at that close in real life.
    The next-bar-open fill closely matches what live trading achieves.
"""
from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from quantify.core.bar import Bar
from quantify.core.event import Direction, FillEvent, OrderEvent


@dataclass(frozen=True, slots=True)
class BrokerConfig:
    commission_rate: float = 0.00025   # 万分之 2.5
    min_commission: float = 5.0        # 单笔最低 5 元
    stamp_tax: float = 0.0005          # 卖出 0.05%
    slippage_bps: float = 5.0          # 5 bps = 0.05%
    # 涨跌停幅度:主板/中小板 0.10,创业板/科创板 0.20。MVP 默认 0.10。
    price_limit_pct: float = 0.10
    lot_size: int = 100                # 整百股下单


class BrokerSim:
    """Simulated A-share broker. Holds pending market orders and fills them at
    the next bar's open."""

    def __init__(self, config: BrokerConfig | None = None) -> None:
        self.config = config or BrokerConfig()
        # 等待下一根 bar 撮合的市价单队列
        self._pending: list[OrderEvent] = []
        # 每标的上一个收盘价,用于涨跌停判定(简化:用昨收作为基准)
        self._prev_close: dict[str, float] = {}

    def submit(self, order: OrderEvent) -> None:
        """Queue a market order for the next bar."""
        if order.quantity <= 0:
            logger.warning("Skip order with non-positive quantity: {}", order)
            return
        # 买入必须是 lot_size 的整数倍(卖出无此限制,可清零股)
        if order.direction == Direction.LONG and order.quantity % self.config.lot_size != 0:
            logger.warning(
                "Buy quantity {} not multiple of lot_size {}, truncating",
                order.quantity, self.config.lot_size,
            )
            qty = (order.quantity // self.config.lot_size) * self.config.lot_size
            if qty <= 0:
                return
            order = OrderEvent(
                timestamp=order.timestamp,
                symbol=order.symbol,
                direction=order.direction,
                quantity=qty,
                order_type=order.order_type,
                limit_price=order.limit_price,
            )
        self._pending.append(order)

    def on_bar(self, bar: Bar) -> list[FillEvent]:
        """Match pending orders for `bar.symbol` against this bar's open.

        Returns the FillEvents produced (may be empty). Orders that survive
        (no matching symbol on this bar) stay in the queue.
        """
        if not self._pending:
            self._prev_close[bar.symbol] = bar.close
            return []

        fills: list[FillEvent] = []
        still_pending: list[OrderEvent] = []

        for order in self._pending:
            if order.symbol != bar.symbol:
                still_pending.append(order)
                continue

            fill = self._try_fill(order, bar)
            if fill is None:
                # 涨跌停被拒绝、或其他原因 — 弃单(实盘对应"未成交撤单")
                logger.info(
                    "Order rejected (likely limit hit): {} {} {} qty={}",
                    bar.timestamp.date(), order.direction, order.symbol, order.quantity,
                )
            else:
                fills.append(fill)

        self._pending = still_pending
        self._prev_close[bar.symbol] = bar.close
        return fills

    # ----- internals -----
    def _try_fill(self, order: OrderEvent, bar: Bar) -> FillEvent | None:
        cfg = self.config
        prev_close = self._prev_close.get(order.symbol)

        # 涨跌停判定:用 bar 当日开盘价 vs 昨收
        if prev_close is not None:
            limit_up = round(prev_close * (1 + cfg.price_limit_pct), 2)
            limit_down = round(prev_close * (1 - cfg.price_limit_pct), 2)
            # 简化:若开盘已涨停 → 买入失败(卖出仍可成交,假设是限价砸盘可成);
            # 若开盘已跌停 → 卖出失败。
            if order.direction == Direction.LONG and bar.open >= limit_up:
                return None
            if order.direction in (Direction.SHORT, Direction.EXIT) and bar.open <= limit_down:
                return None

        # 滑点:买入价上浮,卖出价下浮(对自己不利的方向)
        slip = cfg.slippage_bps / 10_000.0
        if order.direction == Direction.LONG:
            fill_price = bar.open * (1 + slip)
        else:
            fill_price = bar.open * (1 - slip)
        fill_price = round(fill_price, 2)

        gross = fill_price * order.quantity
        commission = max(gross * cfg.commission_rate, cfg.min_commission)
        # 印花税:仅卖出
        tax = gross * cfg.stamp_tax if order.direction != Direction.LONG else 0.0

        return FillEvent(
            timestamp=bar.timestamp,
            symbol=order.symbol,
            direction=order.direction,
            quantity=order.quantity,
            fill_price=fill_price,
            commission=round(commission, 2),
            tax=round(tax, 2),
        )

    def pending_count(self) -> int:
        return len(self._pending)
