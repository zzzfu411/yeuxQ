"""Plotting helpers: equity curve + drawdown + trade markers.

We deliberately use matplotlib (no plotly/bokeh) — fewer deps, easy PNG export,
zero browser dependency. Output is a single PNG with two stacked axes.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

from quantify.core.event import FillEvent

# Use non-interactive backend so plots can be generated in headless contexts (CI).
matplotlib.use("Agg")


def plot_equity(
    equity_curve: list[tuple[datetime, float]],
    fills: list[FillEvent],
    output_path: str | Path,
    title: str = "Backtest equity",
) -> Path:
    """Draw equity + drawdown + buy/sell markers and save to PNG."""
    if not equity_curve:
        raise ValueError("Empty equity curve")

    s = pd.Series(
        [eq for _, eq in equity_curve],
        index=pd.DatetimeIndex([ts for ts, _ in equity_curve]),
    )
    cummax = s.cummax()
    drawdown = (s / cummax - 1) * 100  # percent

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11, 7), sharex=True,
        gridspec_kw={"height_ratios": [3, 1]},
    )

    # ---- Equity curve ----
    ax1.plot(s.index, s.values, linewidth=1.4, label="Equity", color="#1f77b4")
    ax1.set_title(title, fontsize=12)
    ax1.set_ylabel("Equity (CNY)")
    ax1.grid(True, linestyle="--", alpha=0.4)

    # Buy/Sell markers — overlay on the equity curve at the fill timestamp
    if fills:
        df_f = pd.DataFrame(
            [
                {
                    "ts": f.timestamp,
                    "direction": f.direction.value,
                }
                for f in fills
            ]
        )
        # Map fill ts to equity. Multiple symbols can trade on the same
        # rebalance day, so keep the lookup index unique to avoid duplicate
        # label expansion when selecting equity values.
        fill_index = pd.DatetimeIndex(df_f["ts"]).unique()
        s_lookup = s.reindex(s.index.union(fill_index)).ffill()
        for d, marker, color in [("LONG", "^", "#2ca02c"), ("EXIT", "v", "#d62728"), ("SHORT", "v", "#d62728")]:
            sub = df_f[df_f["direction"] == d]
            if not sub.empty:
                eq_at_fill = [s_lookup.loc[ts] for ts in pd.DatetimeIndex(sub["ts"])]
                ax1.scatter(sub["ts"], eq_at_fill, marker=marker, color=color, s=42,
                            label=d, zorder=5, edgecolor="black", linewidth=0.4)

    ax1.legend(loc="upper left")

    # ---- Drawdown ----
    ax2.fill_between(drawdown.index, drawdown.values, 0, color="#d62728", alpha=0.4)
    ax2.set_ylabel("Drawdown (%)")
    ax2.grid(True, linestyle="--", alpha=0.4)
    ax2.set_ylim(min(drawdown.min() * 1.1, -1), 1)

    fig.tight_layout()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=110)
    plt.close(fig)
    return output_path
