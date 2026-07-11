"""Event-driven backtest engine — the heart of the system.

Loop:
    for each bar in chronological order:
        1. Portfolio.on_new_day(bar.date)            # T+1 release
        2. Broker.on_bar(bar) → FillEvents           # match pending orders
           apply each fill to Portfolio
        3. Strategy.on_bar(bar) → SignalEvents
        4. Risk.process(signal) → OrderEvent        # size / reject
           submit OrderEvent to Broker
        5. Portfolio.record_equity(bar.date, prices) # snapshot net worth
        6. Risk.update_equity(equity)                # DD tracking

The engine is a thin orchestrator — all market logic lives in BrokerSim,
all strategy logic in Strategy, all sizing in Risk. This separation lets us
swap BrokerSim with a real-broker adapter later without touching anything else.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from loguru import logger

from quantify.core.event import FillEvent
from quantify.core.portfolio import Portfolio
from quantify.data.base import DataFeed
from quantify.engine.broker_sim import BrokerSim
from quantify.risk.manager import RiskManager
from quantify.strategy.base import Strategy


@dataclass
class BacktestResult:
    portfolio: Portfolio
    initial_cash: float
    final_equity: float
    n_bars: int
    n_signals: int
    n_orders: int
    n_fills: int
    fills: list[FillEvent] = field(default_factory=list)


class BacktestEngine:
    def __init__(
        self,
        data_feed: DataFeed,
        strategy: Strategy,
        broker: BrokerSim,
        risk: RiskManager,
        portfolio: Portfolio,
    ) -> None:
        self.data_feed = data_feed
        self.strategy = strategy
        self.broker = broker
        self.risk = risk
        self.portfolio = portfolio

    def run(
        self,
        symbols: list[str],
        start: str | date,
        end: str | date,
    ) -> BacktestResult:
        """Iterate over bars, drive the event pipeline, return summary."""
        logger.info(
            "Backtest start: symbols={} range={}~{} cash={}",
            symbols, start, end, self.portfolio.initial_cash,
        )
        self.strategy.on_init()

        n_bars = n_signals = n_orders = n_fills = 0
        last_prices: dict[str, float] = {}

        for bar in self.data_feed.stream(symbols, start, end):
            n_bars += 1

            # 1) T+1 释放(新一天到来时)
            self.portfolio.on_new_day(bar.timestamp.date())

            # 2) 撮合上一根 bar 排队的市价单(用当前 bar 的开盘价成交)
            fills = self.broker.on_bar(bar)
            for fill in fills:
                self.portfolio.apply_fill(fill)
                n_fills += 1

            # 3) 策略产生信号
            signals = self.strategy.on_bar(bar)
            n_signals += len(signals)

            # 4) 风控转订单 → 提交 broker(下一根 bar 撮合)
            for sig in signals:
                order = self.risk.process(sig, self.portfolio, ref_price=bar.close)
                if order is not None:
                    self.broker.submit(order)
                    n_orders += 1

            # 5) 记录净值(用当前 bar 收盘价估值)
            last_prices[bar.symbol] = bar.close
            self.portfolio.record_equity(bar.timestamp, last_prices)

            # 6) 风控盯净值
            self.risk.update_equity(self.portfolio.total_equity(last_prices))

        self.strategy.on_finish()

        final_eq = self.portfolio.total_equity(last_prices)
        logger.info(
            "Backtest done: bars={} signals={} orders={} fills={} final_equity={:.2f}",
            n_bars, n_signals, n_orders, n_fills, final_eq,
        )
        return BacktestResult(
            portfolio=self.portfolio,
            initial_cash=self.portfolio.initial_cash,
            final_equity=final_eq,
            n_bars=n_bars,
            n_signals=n_signals,
            n_orders=n_orders,
            n_fills=n_fills,
            fills=list(self.portfolio.trade_log),
        )
