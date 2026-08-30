from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from quantify.core.event import PortfolioTarget
from quantify.core.portfolio import Portfolio
from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.engine.paper_broker import PaperBroker, PaperBrokerConfig
from quantify.research.engine import ResearchEngine


class _FixedUniverse:
    def symbols(self, as_of: str, data: DataProvider) -> list[str]:
        del as_of, data
        return ["AAA"]


class _FixedPipeline:
    def composite_scores(
        self,
        as_of: str,
        universe: list[str],
        data: DataProvider,
    ) -> pd.DataFrame:
        del universe, data
        return pd.DataFrame({"date": [as_of], "symbol": ["AAA"], "score": [1.0]})


class _FixedStrategy:
    universe_filter = _FixedUniverse()

    def on_rebalance(
        self,
        as_of: str,
        data: DataProvider,
        portfolio: Portfolio,
    ) -> list[PortfolioTarget]:
        del data, portfolio
        return [PortfolioTarget(datetime.fromisoformat(as_of), "AAA", 1.0, 1.0)]


def test_research_signals_at_close_and_fills_at_next_open(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "research.db")
    storage.save_stock_info(pd.DataFrame({"symbol": ["AAA"], "name": ["AAA"]}))
    storage.save_calendar(["2024-01-02", "2024-01-03"])
    storage.save_bars(
        pd.DataFrame(
            {
                "symbol": ["AAA", "AAA"],
                "date": ["2024-01-02", "2024-01-03"],
                "open": [9.0, 20.0],
                "high": [11.0, 31.0],
                "low": [8.0, 19.0],
                "close": [10.0, 30.0],
                "volume": [10_000.0, 10_000.0],
                "amount": [100_000.0, 300_000.0],
            }
        )
    )
    provider = DataProvider(storage)
    pipeline = _FixedPipeline()
    engine = ResearchEngine(
        provider,
        _FixedStrategy(),  # type: ignore[arg-type]
        PaperBroker(
            PaperBrokerConfig(
                commission_rate=0,
                min_commission=0,
                stamp_tax=0,
                slippage_bps=0,
                lot_size=1,
                price_limit_pct=10.0,
            )
        ),
        Portfolio(initial_cash=1_000.0),
        pipeline,  # type: ignore[arg-type]
    )

    result = engine.run("2024-01-02", "2024-01-03", rebalance="monthly")

    assert len(result.fills) == 1
    assert result.fills[0].timestamp.date().isoformat() == "2024-01-03"
    assert result.fills[0].fill_price == pytest.approx(20.0)
    assert result.fills[0].quantity == 50
    assert result.turnover[0]["signal_date"] == "2024-01-02"
    assert result.turnover[0]["date"] == "2024-01-03"
