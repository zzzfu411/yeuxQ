"""Tests for analytics: known sequences should produce known metric values."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from quantify.analytics.metrics import compute_report
from quantify.analytics.plot import plot_equity
from quantify.core.event import Direction, FillEvent


def _curve(values: list[float], start: datetime | None = None) -> list[tuple[datetime, float]]:
    start = start or datetime(2024, 1, 1)
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


def test_metrics_no_change_zero_return() -> None:
    curve = _curve([100.0] * 10)
    rep = compute_report(curve, fills=[])
    assert rep.total_return == pytest.approx(0.0)
    assert rep.max_drawdown == pytest.approx(0.0)
    assert rep.sharpe_ratio == 0.0  # zero variance


def test_metrics_pure_uptrend_positive_sharpe() -> None:
    # +1% per day for 252 days
    values = [100.0 * (1.01 ** i) for i in range(252)]
    rep = compute_report(_curve(values), fills=[])
    assert rep.total_return > 10  # ~12.0
    assert rep.annualized_return > 1.0  # > 100% annualized (because daily +1%)
    assert rep.sharpe_ratio > 5  # extremely high (no volatility)
    assert rep.max_drawdown == pytest.approx(0.0)


def test_metrics_max_drawdown_calculation() -> None:
    # Peak 200, trough 100 → 50% drawdown
    curve = _curve([100, 150, 200, 150, 100, 120, 130])
    rep = compute_report(curve, fills=[])
    assert rep.max_drawdown == pytest.approx(0.5)


def test_metrics_round_trip_win_rate() -> None:
    fills = [
        # Buy 100 @ 10 (cost 1000)
        FillEvent(datetime(2024, 1, 2), "X", Direction.LONG, 100, 10.0, 0, 0),
        # Sell 100 @ 12 (proceeds 1200) → win
        FillEvent(datetime(2024, 1, 5), "X", Direction.EXIT, 100, 12.0, 0, 0),
        # Buy 100 @ 15 (cost 1500)
        FillEvent(datetime(2024, 1, 8), "X", Direction.LONG, 100, 15.0, 0, 0),
        # Sell 100 @ 14 (proceeds 1400) → loss
        FillEvent(datetime(2024, 1, 11), "X", Direction.EXIT, 100, 14.0, 0, 0),
    ]
    curve = _curve([100_000, 100_000, 100_200, 100_300, 100_200, 100_100])  # filler
    rep = compute_report(curve, fills=fills)
    assert rep.n_round_trips == 2
    assert rep.win_rate == pytest.approx(0.5)


def test_plot_equity_writes_png(tmp_path: Path) -> None:
    fills = [
        FillEvent(datetime(2024, 1, 3), "X", Direction.LONG, 100, 100.0, 0, 0),
        FillEvent(datetime(2024, 1, 8), "X", Direction.EXIT, 100, 110.0, 0, 0),
    ]
    curve = _curve([100_000.0 + i * 10 for i in range(20)])
    out = plot_equity(curve, fills, tmp_path / "eq.png", title="Test")
    assert out.exists()
    assert out.stat().st_size > 1000  # not an empty file
