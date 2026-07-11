"""Target-weight multi-factor strategy."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from quantify.core.event import PortfolioTarget
from quantify.core.portfolio import Portfolio
from quantify.data.provider import DataProvider
from quantify.research.factors import FactorPipeline
from quantify.research.universe import UniverseFilter


@dataclass(frozen=True, slots=True)
class MultiFactorStrategyConfig:
    n_holdings: int = 30
    max_weight: float = 0.05
    hold_rank_buffer: int = 0
    min_trade_weight: float = 0.0
    max_new_positions: int = 0
    score_smoothing_observations: int = 0
    score_smoothing_step_days: int = 20


class MultiFactorTargetStrategy:
    """Select top-scoring symbols and emit target weights."""

    def __init__(
        self,
        universe_filter: UniverseFilter,
        factor_pipeline: FactorPipeline,
        config: MultiFactorStrategyConfig | None = None,
    ) -> None:
        self.universe_filter = universe_filter
        self.factor_pipeline = factor_pipeline
        self.config = config or MultiFactorStrategyConfig()

    def on_rebalance(
        self,
        as_of: str,
        data: DataProvider,
        portfolio: Portfolio,
    ) -> list[PortfolioTarget]:
        universe = self.universe_filter.symbols(as_of, data)
        scores = self._scores_for_selection(as_of, universe, data)
        if scores.empty:
            return []

        chosen = self._select_with_hold_buffer(scores, portfolio)
        if chosen.empty:
            return []
        equal_weight = min(1.0 / len(chosen), self.config.max_weight)
        ts = datetime.fromisoformat(as_of)
        prices = self._prices_for_weight_drift(as_of, data, chosen, portfolio)
        equity = portfolio.total_equity(prices) if prices else 0.0
        return [
            PortfolioTarget(
                timestamp=ts,
                symbol=str(row.symbol),
                target_weight=self._target_weight_after_drift_band(
                    str(row.symbol),
                    equal_weight,
                    portfolio,
                    prices,
                    equity,
                ),
                score=float(row.score),
            )
            for row in chosen.itertuples(index=False)
        ]

    def _scores_for_selection(
        self,
        as_of: str,
        universe: list[str],
        data: DataProvider,
    ):
        observations = max(int(self.config.score_smoothing_observations), 0)
        if observations <= 1:
            return self.factor_pipeline.composite_scores(as_of, universe, data)
        frames = []
        for score_date in self._score_smoothing_dates(as_of, data, observations):
            frame = self.factor_pipeline.composite_scores(score_date, universe, data)
            if frame.empty:
                continue
            frames.append(frame[["symbol", "score"]])
        if not frames:
            return self.factor_pipeline.composite_scores(as_of, universe, data)
        smoothed = (
            pd.concat(frames, ignore_index=True)
            .groupby("symbol", as_index=False)["score"]
            .mean()
            .sort_values("score", ascending=False)
        )
        return smoothed.assign(date=as_of)[["date", "symbol", "score"]]

    def _score_smoothing_dates(
        self,
        as_of: str,
        data: DataProvider,
        observations: int,
    ) -> list[str]:
        step = max(int(self.config.score_smoothing_step_days), 1)
        start = (
            datetime.fromisoformat(as_of) - timedelta(days=observations * step * 3 + 7)
        ).date().isoformat()
        days = [str(day) for day in data.trading_days(start, as_of) if str(day) <= as_of]
        if as_of not in days:
            days.append(as_of)
            days = sorted(set(days))
        selected = []
        idx = len(days) - 1
        while idx >= 0 and len(selected) < observations:
            selected.append(str(days[idx]))
            idx -= step
        return list(reversed(selected))

    def _select_with_hold_buffer(
        self,
        scores,
        portfolio: Portfolio,
    ):
        n = max(int(self.config.n_holdings), 0)
        if n <= 0:
            return scores.head(0).copy()
        buffer = max(int(self.config.hold_rank_buffer), 0)
        max_new_positions = max(int(self.config.max_new_positions), 0)
        if (buffer <= 0 and max_new_positions <= 0) or not portfolio.positions:
            return scores.head(n).copy()
        ranked = scores.reset_index(drop=True).copy()
        eligible = ranked.head(n + buffer)
        eligible_symbols = set(eligible["symbol"].astype(str)) if buffer > 0 else set(ranked["symbol"].astype(str))
        held_symbol_set = {
            symbol
            for symbol, position in portfolio.positions.items()
            if position.total_qty > 0
        }
        held_symbols = [
            symbol
            for symbol, position in portfolio.positions.items()
            if position.total_qty > 0 and symbol in eligible_symbols
        ]
        if max_new_positions > 0:
            held_symbols = [
                symbol
                for symbol in ranked["symbol"].astype(str)
                if symbol in held_symbol_set and symbol in eligible_symbols
            ]
        selected: list[str] = []
        for symbol in held_symbols:
            if symbol not in selected:
                selected.append(symbol)
            if len(selected) >= n:
                break
        new_position_count = 0
        for symbol in ranked["symbol"].astype(str):
            if symbol not in selected:
                if (
                    max_new_positions > 0
                    and symbol not in held_symbol_set
                    and new_position_count >= max_new_positions
                ):
                    continue
                selected.append(symbol)
                if symbol not in held_symbol_set:
                    new_position_count += 1
            if len(selected) >= n:
                break
        order = {symbol: idx for idx, symbol in enumerate(selected)}
        chosen = ranked[ranked["symbol"].astype(str).isin(set(order))].copy()
        chosen["_selection_order"] = chosen["symbol"].astype(str).map(order)
        return chosen.sort_values("_selection_order").drop(columns=["_selection_order"])

    def _prices_for_weight_drift(
        self,
        as_of: str,
        data: DataProvider,
        chosen,
        portfolio: Portfolio,
    ) -> dict[str, float]:
        if self.config.min_trade_weight <= 0:
            return {}
        symbols = set(chosen["symbol"].astype(str))
        symbols.update(
            symbol for symbol, position in portfolio.positions.items() if position.total_qty > 0
        )
        return data.latest_prices(sorted(symbols), as_of)

    def _target_weight_after_drift_band(
        self,
        symbol: str,
        target_weight: float,
        portfolio: Portfolio,
        prices: dict[str, float],
        equity: float,
    ) -> float:
        threshold = max(float(self.config.min_trade_weight), 0.0)
        if threshold <= 0 or equity <= 0:
            return target_weight
        position = portfolio.positions.get(symbol)
        price = prices.get(symbol)
        if position is None or position.total_qty <= 0 or price is None:
            return target_weight
        current_weight = position.total_qty * price / equity
        if current_weight <= self.config.max_weight and abs(target_weight - current_weight) < threshold:
            return current_weight
        return target_weight
