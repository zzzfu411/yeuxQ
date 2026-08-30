"""Performance metrics for an equity curve.

All metrics are computed from a list of (timestamp, equity) tuples. We expose:
    - total_return:        final / initial - 1
    - annualized_return:   geometric, assumes 252 trading days/year
    - annualized_volatility
    - sharpe_ratio:        rf=0 by default
    - max_drawdown:        worst peak-to-trough as a positive fraction
    - win_rate:            % of profitable closed round-trips (computed from fills)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from quantify.core.event import Direction, FillEvent

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    initial_equity: float
    final_equity: float
    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe_ratio: float
    max_drawdown: float
    n_round_trips: int
    win_rate: float
    n_bars: int

    def to_dict(self) -> dict[str, float | int]:
        return {
            "initial_equity": self.initial_equity,
            "final_equity": self.final_equity,
            "total_return": self.total_return,
            "annualized_return": self.annualized_return,
            "annualized_volatility": self.annualized_volatility,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "n_round_trips": self.n_round_trips,
            "win_rate": self.win_rate,
            "n_bars": self.n_bars,
        }


def compute_report(
    equity_curve: list[tuple[datetime, float]],
    fills: list[FillEvent],
    risk_free_rate: float = 0.0,
    *,
    initial_equity: float | None = None,
) -> PerformanceReport:
    if len(equity_curve) < 2:
        raise ValueError("Need ≥2 equity samples to compute returns")

    curve = pd.Series(
        [eq for _, eq in equity_curve],
        index=pd.DatetimeIndex([ts for ts, _ in equity_curve]),
    ).astype(float)

    if initial_equity is None:
        s = curve
        n_periods = len(curve) - 1
    else:
        initial_value = float(initial_equity)
        if not np.isfinite(initial_value) or initial_value <= 0:
            raise ValueError("initial_equity must be a positive finite number")
        s = pd.Series([initial_value, *curve.tolist()], dtype=float)
        n_periods = len(curve)

    initial = s.iloc[0]
    final = s.iloc[-1]
    total_ret = final / initial - 1

    # 年化:用实际交易日数,假设每个 equity 点 = 1 个交易日
    if n_periods > 0:
        ann_ret = (final / initial) ** (TRADING_DAYS_PER_YEAR / n_periods) - 1
    else:
        ann_ret = 0.0

    daily_ret = s.pct_change().dropna()
    ann_vol = daily_ret.std() * np.sqrt(TRADING_DAYS_PER_YEAR) if len(daily_ret) > 1 else 0.0

    excess = daily_ret - (risk_free_rate / TRADING_DAYS_PER_YEAR)
    sharpe = (excess.mean() / excess.std()) * np.sqrt(TRADING_DAYS_PER_YEAR) if excess.std() > 0 else 0.0

    # 最大回撤:从 cummax 到当前的最大相对损失
    cummax = s.cummax()
    drawdown = 1 - s / cummax
    max_dd = drawdown.max()

    n_rt, win_rate = _round_trip_stats(fills)

    return PerformanceReport(
        initial_equity=float(initial),
        final_equity=float(final),
        total_return=float(total_ret),
        annualized_return=float(ann_ret),
        annualized_volatility=float(ann_vol),
        sharpe_ratio=float(sharpe),
        max_drawdown=float(max_dd),
        n_round_trips=n_rt,
        win_rate=float(win_rate),
        n_bars=len(curve),
    )


def _round_trip_stats(fills: list[FillEvent]) -> tuple[int, float]:
    """Pair each EXIT with the most recent LONG of the same symbol; FIFO accounting.

    Returns (round_trip_count, win_rate). Win = sell proceeds > buy cost net of fees.
    """
    # 按 symbol 维护买入队列 [(qty, total_cost), ...]
    buys: dict[str, list[tuple[int, float]]] = {}
    wins = 0
    rts = 0

    for f in sorted(fills, key=lambda x: x.timestamp):
        if f.direction == Direction.LONG:
            buys.setdefault(f.symbol, []).append((f.quantity, f.total_cost))
        else:  # EXIT / SHORT
            sell_proceeds_per_share = (f.gross_value - f.commission - f.tax) / f.quantity
            qty_remaining = f.quantity
            queue = buys.get(f.symbol, [])
            cost_used = 0.0
            qty_matched = 0
            while qty_remaining > 0 and queue:
                bq, bc = queue[0]
                cost_per_share = bc / bq
                use = min(qty_remaining, bq)
                cost_used += cost_per_share * use
                qty_matched += use
                qty_remaining -= use
                if use == bq:
                    queue.pop(0)
                else:
                    queue[0] = (bq - use, bc - cost_per_share * use)
            if qty_matched > 0:
                rts += 1
                proceeds = sell_proceeds_per_share * qty_matched
                if proceeds > cost_used:
                    wins += 1

    win_rate = wins / rts if rts else 0.0
    return rts, win_rate
