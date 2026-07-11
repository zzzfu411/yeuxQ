"""Daily research engine for target-weight strategies."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from quantify.core.event import FillEvent
from quantify.core.portfolio import Portfolio
from quantify.data.provider import DataProvider
from quantify.engine.paper_broker import PaperBroker, PaperOrder
from quantify.research.factors import FactorPipeline, rank_ic
from quantify.research.strategy import MultiFactorTargetStrategy


@dataclass(slots=True)
class ResearchResult:
    portfolio: Portfolio
    equity_curve: list[tuple[datetime, float]]
    fills: list[FillEvent] = field(default_factory=list)
    orders: list[PaperOrder] = field(default_factory=list)
    positions: list[dict[str, object]] = field(default_factory=list)
    turnover: list[dict[str, object]] = field(default_factory=list)
    factor_scores: pd.DataFrame = field(default_factory=pd.DataFrame)
    factor_ic: pd.DataFrame = field(default_factory=pd.DataFrame)


class ResearchEngine:
    def __init__(
        self,
        data: DataProvider,
        strategy: MultiFactorTargetStrategy,
        broker: PaperBroker,
        portfolio: Portfolio,
        factor_pipeline: FactorPipeline,
        max_drawdown_stop: float = 0.2,
    ) -> None:
        self.data = data
        self.strategy = strategy
        self.broker = broker
        self.portfolio = portfolio
        self.factor_pipeline = factor_pipeline
        self.max_drawdown_stop = max_drawdown_stop
        self._halted = False
        self._peak_equity = portfolio.initial_cash

    def run(self, start: str, end: str, rebalance: str = "M") -> ResearchResult:
        days = self.data.trading_days(start, end)
        if not days:
            raise ValueError("No trading days or cached bars found for research range")
        rebalance_days = set(_rebalance_days(days, rebalance))

        factor_frames: list[pd.DataFrame] = []
        fills: list[FillEvent] = []
        orders: list[PaperOrder] = []
        turnover_rows: list[dict[str, object]] = []
        position_rows: list[dict[str, object]] = []
        last_prices: dict[str, float] = {}
        prev_prices: dict[str, float] = {}

        all_symbols = self.data.all_symbols()
        for day in days:
            self.portfolio.on_new_day(datetime.fromisoformat(day).date())
            prices = self.data.latest_prices(all_symbols, day)
            if prices:
                prev_prices = last_prices
                last_prices = prices

            if day in rebalance_days and not self._halted:
                universe = self.strategy.universe_filter.symbols(day, self.data)
                scores = self.factor_pipeline.composite_scores(day, universe, self.data)
                if not scores.empty:
                    factor_frames.append(scores.assign(kind="composite"))
                targets = self.strategy.on_rebalance(day, self.data, self.portfolio)
                result = self.broker.rebalance(
                    targets,
                    prices,
                    self.portfolio,
                    suspended=self.data.suspended_symbols(day),
                    prev_closes=prev_prices,
                )
                fills.extend(result.fills)
                orders.extend(result.orders)
                equity_before_turnover = max(self.portfolio.total_equity(prices), 1.0)
                turnover_rows.append(
                    {
                        "date": day,
                        "turnover": result.turnover,
                        "turnover_pct": result.turnover / equity_before_turnover,
                    }
                )

            equity = self.portfolio.total_equity(last_prices)
            self.portfolio.record_equity(datetime.fromisoformat(day), last_prices)
            self._update_drawdown_halt(equity)
            position_rows.extend(_snapshot_positions(day, self.portfolio, last_prices))

        factor_scores = pd.concat(factor_frames, ignore_index=True) if factor_frames else pd.DataFrame()
        factor_ic = self._compute_factor_ic(factor_scores, days, all_symbols)
        return ResearchResult(
            portfolio=self.portfolio,
            equity_curve=self.portfolio.equity_curve,
            fills=fills,
            orders=orders,
            positions=position_rows,
            turnover=turnover_rows,
            factor_scores=factor_scores,
            factor_ic=factor_ic,
        )

    def _update_drawdown_halt(self, equity: float) -> None:
        self._peak_equity = max(self._peak_equity, equity)
        if self._peak_equity <= 0:
            return
        drawdown = 1 - equity / self._peak_equity
        if drawdown >= self.max_drawdown_stop:
            self._halted = True

    def _compute_factor_ic(
        self,
        scores: pd.DataFrame,
        days: list[str],
        symbols: list[str],
    ) -> pd.DataFrame:
        if scores.empty:
            return pd.DataFrame(columns=["date", "rank_ic"])
        close = self.data.close_matrix(symbols, days[0], days[-1])
        if close.empty:
            return pd.DataFrame(columns=["date", "rank_ic"])
        rows = []
        by_date = scores.groupby("date")
        for day, frame in by_date:
            if day not in close.index:
                continue
            loc = close.index.get_loc(day)
            if not isinstance(loc, int) or loc + 1 >= len(close.index):
                continue
            next_day = close.index[loc + 1]
            forward = close.loc[next_day] / close.loc[day] - 1
            score = frame.set_index("symbol")["score"]
            rows.append({"date": day, "rank_ic": rank_ic(score, forward)})
        return pd.DataFrame(rows)


def _rebalance_days(days: list[str], freq: str) -> list[str]:
    if freq.upper().startswith("W"):
        periods = pd.to_datetime(days).to_period("W")
    elif freq.upper().startswith("Q"):
        periods = pd.to_datetime(days).to_period("Q")
    else:
        periods = pd.to_datetime(days).to_period("M")
    frame = pd.DataFrame({"date": days, "period": periods})
    return frame.groupby("period")["date"].first().tolist()


def _snapshot_positions(
    day: str,
    portfolio: Portfolio,
    prices: dict[str, float],
) -> list[dict[str, object]]:
    rows = []
    equity = max(portfolio.total_equity(prices), 1.0)
    for symbol, pos in portfolio.positions.items():
        if pos.total_qty <= 0:
            continue
        price = prices.get(symbol, pos.avg_cost)
        market_value = pos.total_qty * price
        rows.append(
            {
                "date": day,
                "symbol": symbol,
                "quantity": pos.total_qty,
                "available_qty": pos.available_qty,
                "price": price,
                "market_value": market_value,
                "weight": market_value / equity,
                "avg_cost": pos.avg_cost,
            }
        )
    return rows
