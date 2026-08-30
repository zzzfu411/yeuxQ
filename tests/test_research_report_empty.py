from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from quantify.core.portfolio import Portfolio
from quantify.research.engine import ResearchResult
from quantify.research.report import write_research_report


def test_empty_research_artifacts_keep_readable_csv_schemas(tmp_path: Path) -> None:
    start = datetime(2024, 1, 2)
    result = ResearchResult(
        portfolio=Portfolio(initial_cash=100_000.0),
        equity_curve=[(start, 100_000.0), (start + timedelta(days=1), 100_000.0)],
    )

    output = write_research_report(result, tmp_path / "report", "Empty research")

    assert list(pd.read_csv(output / "positions.csv")) == [
        "date",
        "symbol",
        "quantity",
        "available_qty",
        "price",
        "market_value",
        "weight",
        "avg_cost",
    ]
    assert list(pd.read_csv(output / "orders.csv")) == [
        "timestamp",
        "symbol",
        "direction",
        "quantity",
        "price",
        "status",
        "reason",
    ]
    assert list(pd.read_csv(output / "trades.csv")) == [
        "timestamp",
        "symbol",
        "direction",
        "quantity",
        "fill_price",
        "commission",
        "tax",
        "gross_value",
    ]
    assert list(pd.read_csv(output / "turnover.csv")) == [
        "date",
        "signal_date",
        "turnover",
        "turnover_pct",
    ]
