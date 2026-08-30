from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantify.core.event import Direction, PortfolioTarget
from quantify.core.portfolio import Portfolio, Position
from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.engine.paper_broker import PaperBroker, PaperBrokerConfig
from quantify.research.demo_data import seed_demo_data
from quantify.research.engine import ResearchEngine
from quantify.research.factors import (
    FactorPipeline,
    LiquidityNeutralLongMomentumFactor,
    LongMomentumFactor,
    rank_ic,
)
from quantify.research.report import write_research_report
from quantify.research.strategy import MultiFactorStrategyConfig, MultiFactorTargetStrategy
from quantify.research.turnover import summarize_turnover
from quantify.research.universe import UniverseConfig, UniverseFilter


@pytest.fixture
def seeded_provider(tmp_path: Path) -> DataProvider:
    storage = BarStorage(tmp_path / "research.db")
    seed_demo_data(storage, start="2020-01-01", end="2020-06-30")
    return DataProvider(storage)


def test_storage_research_tables_roundtrip(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "q.db")
    storage.save_stock_info(pd.DataFrame({"symbol": ["AAA"], "name": ["测试A"]}))
    storage.save_calendar(["2024-01-02"])
    storage.save_index_constituents("000906", "2024-01-02", ["AAA"])
    storage.save_fundamentals(
        pd.DataFrame({"symbol": ["AAA"], "date": ["2024-01-02"], "pe_ttm": [10.0], "roe": [0.1]})
    )
    storage.save_metadata({"csv_dataset_fingerprint": "abc123", "source": "unit_test"})

    assert storage.load_stock_info()["symbol"].tolist() == ["AAA"]
    assert storage.load_calendar() == ["2024-01-02"]
    assert storage.load_index_constituents("000906", "2024-01-03") == ["AAA"]
    assert storage.load_fundamentals(["AAA"], "2024-01-03")["pe_ttm"].iloc[0] == pytest.approx(10.0)
    assert storage.load_metadata()["csv_dataset_fingerprint"] == "abc123"


def test_universe_filter_excludes_st_and_suspended(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "q.db")
    storage.save_stock_info(
        pd.DataFrame(
            {
                "symbol": ["AAA", "BBB", "CCC"],
                "name": ["正常", "ST风险", "正常2"],
                "is_st": [0, 1, 0],
            }
        )
    )
    storage.save_bars(
        pd.DataFrame(
            {
                "symbol": ["AAA", "BBB", "CCC"],
                "date": ["2024-01-02"] * 3,
                "open": [10, 10, 10],
                "high": [11, 11, 11],
                "low": [9, 9, 9],
                "close": [10, 10, 10],
                "volume": [1000, 1000, 1000],
                "amount": [10000, 10000, 10000],
            }
        )
    )
    storage.save_suspensions(pd.DataFrame({"symbol": ["CCC"], "date": ["2024-01-02"]}))
    provider = DataProvider(storage)
    symbols = UniverseFilter(UniverseConfig(min_history_days=1)).symbols("2024-01-02", provider)
    assert symbols == ["AAA"]


def test_universe_filter_counts_available_bar_days_without_stock_info(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "history.db")
    dates = pd.bdate_range("2024-01-02", periods=3).date.astype(str).tolist()
    _save_universe_bars(storage, {"AAA": [*dates, "2024-02-01"], "BBB": dates[:2]})
    provider = DataProvider(storage)

    assert UniverseFilter(UniverseConfig(min_history_days=3)).symbols(dates[-1], provider) == ["AAA"]
    assert UniverseFilter(UniverseConfig(min_history_days=4)).symbols(dates[-1], provider) == []
    assert UniverseFilter(UniverseConfig(min_history_days=10_000)).symbols(
        dates[-1], provider
    ) == []


def test_universe_filter_excludes_symbols_listed_after_as_of(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "list_date.db")
    storage.save_stock_info(
        pd.DataFrame(
            {
                "symbol": ["AAA", "BBB"],
                "name": ["AAA", "BBB"],
                "list_date": ["2024-01-03", "2024-01-02"],
            }
        )
    )
    _save_universe_bars(storage, {"AAA": ["2024-01-02"], "BBB": ["2024-01-02"]})

    symbols = UniverseFilter(UniverseConfig(min_history_days=1)).symbols(
        "2024-01-02", DataProvider(storage)
    )

    assert symbols == ["BBB"]


def test_universe_filter_applies_delist_date_only_when_reached(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "delist_date.db")
    storage.save_stock_info(
        pd.DataFrame(
            {
                "symbol": ["AAA"],
                "name": ["AAA"],
                "delist_date": ["2024-01-05"],
            }
        )
    )
    dates = pd.bdate_range("2024-01-02", periods=5).date.astype(str).tolist()
    _save_universe_bars(storage, {"AAA": dates})
    universe_filter = UniverseFilter(UniverseConfig(min_history_days=1))
    provider = DataProvider(storage)

    assert universe_filter.symbols("2024-01-04", provider) == ["AAA"]
    assert universe_filter.symbols("2024-01-05", provider) == []
    assert universe_filter.symbols("2024-01-08", provider) == []


def test_factor_pipeline_scores_and_rank_ic(seeded_provider: DataProvider) -> None:
    universe = seeded_provider.all_symbols()
    pipeline = FactorPipeline()
    scores = pipeline.composite_scores("2020-06-30", universe, seeded_provider)
    assert not scores.empty
    assert {"date", "symbol", "score"}.issubset(scores.columns)
    assert rank_ic(pd.Series([1, 2, 3]), pd.Series([1, 4, 9])) == pytest.approx(1.0)


def test_long_momentum_factor_uses_long_past_window_and_skips_recent_prices(
    tmp_path: Path,
) -> None:
    storage = BarStorage(tmp_path / "long_momentum.db")
    dates = pd.bdate_range("2024-01-02", periods=150).date.astype(str).tolist()
    future = "2024-12-31"
    rows = []
    for idx, day in enumerate([*dates, future], start=1):
        close = 10.0 + idx
        if day == future:
            close = 9999.0
        rows.append(
            {
                "symbol": "AAA",
                "date": day,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1_000_000,
                "amount": close * 1_000_000,
            }
        )
    storage.save_stock_info(pd.DataFrame({"symbol": ["AAA"], "name": ["AAA"]}))
    storage.save_calendar([*dates, future])
    storage.save_bars(pd.DataFrame(rows))
    provider = DataProvider(storage)

    values = LongMomentumFactor().compute(dates[-1], ["AAA"], provider)

    expected = (10.0 + 130) / (10.0 + 30) - 1
    assert values["AAA"] == pytest.approx(expected)
    assert values.name == "long_momentum_120d_skip20d"


def test_liquidity_neutral_long_momentum_residualizes_amount_exposure(
    tmp_path: Path,
) -> None:
    storage = BarStorage(tmp_path / "liquidity_neutral_momentum.db")
    dates = pd.bdate_range("2024-01-02", periods=150).date.astype(str).tolist()
    symbols = ["AAA", "BBB", "CCC", "DDD"]
    momentum_by_symbol = {"AAA": 0.55, "BBB": 0.18, "CCC": 0.12, "DDD": -0.05}
    amount_by_symbol = {"AAA": 400_000_000, "BBB": 250_000_000, "CCC": 90_000_000, "DDD": 30_000_000}
    rows = []
    for symbol in symbols:
        target_return = momentum_by_symbol[symbol]
        for idx, day in enumerate(dates):
            close = 100.0
            if idx >= 129:
                close *= 1.0 + target_return
            rows.append(
                {
                    "symbol": symbol,
                    "date": day,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": amount_by_symbol[symbol] / close,
                    "amount": amount_by_symbol[symbol],
                }
            )
    storage.save_stock_info(pd.DataFrame({"symbol": symbols, "name": symbols}))
    storage.save_calendar(dates)
    storage.save_bars(pd.DataFrame(rows))
    provider = DataProvider(storage)

    values = LiquidityNeutralLongMomentumFactor().compute(dates[-1], symbols, provider)
    liquidity = pd.Series(amount_by_symbol, dtype=float).pipe(np.log1p)
    clipped = liquidity.clip(lower=liquidity.quantile(0.05), upper=liquidity.quantile(0.95))
    liquidity_score = (clipped - clipped.mean()) / clipped.std(ddof=0)
    residual_liquidity_exposure = float((values * liquidity_score).sum())

    assert values.name == "liquidity_neutral_long_momentum_120d_skip20d"
    assert values.notna().sum() == len(symbols)
    assert abs(residual_liquidity_exposure) < 1e-10


def test_target_strategy_retains_holdings_inside_rank_buffer() -> None:
    pipeline = _FixedPipeline(["AAA", "BBB", "CCC", "DDD"])
    strategy = MultiFactorTargetStrategy(
        _FixedUniverse(["AAA", "BBB", "CCC", "DDD"]),
        pipeline,  # type: ignore[arg-type]
        MultiFactorStrategyConfig(n_holdings=2, max_weight=0.5, hold_rank_buffer=2),
    )
    portfolio = Portfolio(initial_cash=10_000.0)
    portfolio.positions["CCC"] = Position(symbol="CCC", total_qty=100, available_qty=100, avg_cost=10.0)

    targets = strategy.on_rebalance("2024-01-02", _StaticData({}), portfolio)  # type: ignore[arg-type]
    symbols = {target.symbol for target in targets}

    assert symbols == {"AAA", "CCC"}


def test_target_strategy_skips_tiny_weight_drift() -> None:
    pipeline = _FixedPipeline(["AAA", "BBB"])
    strategy = MultiFactorTargetStrategy(
        _FixedUniverse(["AAA", "BBB"]),
        pipeline,  # type: ignore[arg-type]
        MultiFactorStrategyConfig(n_holdings=2, max_weight=0.6, min_trade_weight=0.02),
    )
    portfolio = Portfolio(initial_cash=10_000.0)
    portfolio.cash = 5_100.0
    portfolio.positions["AAA"] = Position(symbol="AAA", total_qty=490, available_qty=490, avg_cost=10.0)

    targets = strategy.on_rebalance(
        "2024-01-02",
        _StaticData({"AAA": 10.0, "BBB": 10.0}),  # type: ignore[arg-type]
        portfolio,
    )
    weights = {target.symbol: target.target_weight for target in targets}

    assert weights["AAA"] == pytest.approx(0.49)
    assert weights["BBB"] == pytest.approx(0.50)


def test_target_strategy_limits_new_positions_per_rebalance() -> None:
    pipeline = _FixedPipeline(["AAA", "BBB", "CCC", "DDD", "EEE"])
    strategy = MultiFactorTargetStrategy(
        _FixedUniverse(["AAA", "BBB", "CCC", "DDD", "EEE"]),
        pipeline,  # type: ignore[arg-type]
        MultiFactorStrategyConfig(
            n_holdings=3,
            max_weight=0.5,
            hold_rank_buffer=5,
            max_new_positions=1,
        ),
    )
    portfolio = Portfolio(initial_cash=10_000.0)
    portfolio.positions["DDD"] = Position(symbol="DDD", total_qty=100, available_qty=100, avg_cost=10.0)
    portfolio.positions["EEE"] = Position(symbol="EEE", total_qty=100, available_qty=100, avg_cost=10.0)

    targets = strategy.on_rebalance("2024-01-02", _StaticData({}), portfolio)  # type: ignore[arg-type]
    symbols = [target.symbol for target in targets]

    assert symbols == ["DDD", "EEE", "AAA"]
    assert "BBB" not in symbols


def test_target_strategy_smooths_scores_using_past_dates_only() -> None:
    pipeline = _DatedPipeline(
        {
            "2024-01-01": {"AAA": 3.0, "BBB": 2.0, "CCC": 1.0},
            "2024-01-02": {"AAA": 3.0, "BBB": 2.0, "CCC": 1.0},
            "2024-01-03": {"CCC": 3.0, "BBB": 2.0, "AAA": 1.0},
            "2024-01-04": {"CCC": 9.0, "BBB": 1.0, "AAA": 0.0},
        }
    )
    strategy = MultiFactorTargetStrategy(
        _FixedUniverse(["AAA", "BBB", "CCC"]),
        pipeline,  # type: ignore[arg-type]
        MultiFactorStrategyConfig(
            n_holdings=2,
            max_weight=0.5,
            score_smoothing_observations=3,
            score_smoothing_step_days=1,
        ),
    )

    targets = strategy.on_rebalance(
        "2024-01-03",
        _StaticData(
            {},
            trading_days=["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
        ),  # type: ignore[arg-type]
        Portfolio(initial_cash=10_000.0),
    )

    assert [target.symbol for target in targets] == ["AAA", "BBB"]
    assert pipeline.calls == ["2024-01-01", "2024-01-02", "2024-01-03"]
    assert "2024-01-04" not in pipeline.calls


def test_turnover_summary_splits_initial_and_maintenance_turnover() -> None:
    summary = summarize_turnover(
        [
            {"turnover_pct": 0.80},
            {"turnover_pct": 0.10},
            {"turnover_pct": 0.30},
        ]
    )

    assert summary["initial_turnover_pct"] == pytest.approx(0.80)
    assert summary["maintenance_turnover_observation_count"] == 2
    assert summary["avg_maintenance_turnover_pct"] == pytest.approx(0.20)
    assert summary["max_maintenance_turnover_pct"] == pytest.approx(0.30)


def test_paper_broker_rebalance_respects_lots_and_cash(seeded_provider: DataProvider) -> None:
    portfolio = Portfolio(initial_cash=10_000.0)
    broker = PaperBroker(PaperBrokerConfig(commission_rate=0, min_commission=0, stamp_tax=0, slippage_bps=0))
    prices = {"DEMO001": 10.0, "DEMO002": 1000.0}
    targets = [
        PortfolioTarget(datetime(2020, 6, 1), "DEMO001", 0.5),
        PortfolioTarget(datetime(2020, 6, 1), "DEMO002", 0.5),
    ]
    result = broker.rebalance(targets, prices, portfolio)
    assert result.fills
    assert all(fill.quantity % 100 == 0 for fill in result.fills if fill.direction == Direction.LONG)
    below_lot = [order for order in result.orders if order.reason == "below_lot"]
    assert len(below_lot) == 1
    assert below_lot[0].symbol == "DEMO002"
    assert below_lot[0].status == "rejected"
    assert 0 < below_lot[0].quantity < 100
    assert portfolio.cash >= 0


def test_paper_broker_records_t_plus_one_sell_rejection() -> None:
    portfolio = Portfolio(initial_cash=10_000.0)
    portfolio.positions["AAA"] = Position(
        symbol="AAA",
        total_qty=500,
        available_qty=200,
        avg_cost=10.0,
        bought_today=300,
    )
    broker = PaperBroker(PaperBrokerConfig(commission_rate=0, min_commission=0, stamp_tax=0, slippage_bps=0))

    result = broker.rebalance([], {"AAA": 10.0}, portfolio)

    filled = [order for order in result.orders if order.status == "filled"]
    rejected = [order for order in result.orders if order.status == "rejected"]
    assert filled[0].quantity == 200
    assert rejected[0].reason == "t_plus_one"
    assert rejected[0].quantity == 300
    assert portfolio.positions["AAA"].total_qty == 300
    assert portfolio.positions["AAA"].available_qty == 0


def test_paper_broker_rejects_suspension_and_price_limits() -> None:
    portfolio = Portfolio(initial_cash=10_000.0)
    portfolio.positions["DOWN"] = Position(symbol="DOWN", total_qty=100, available_qty=100, avg_cost=10.0)
    broker = PaperBroker(PaperBrokerConfig(commission_rate=0, min_commission=0, stamp_tax=0, slippage_bps=0))
    targets = [
        PortfolioTarget(datetime(2024, 1, 3), "HALT", 0.5),
        PortfolioTarget(datetime(2024, 1, 3), "UP", 0.5),
    ]

    result = broker.rebalance(
        targets,
        {"HALT": 10.0, "UP": 11.0, "DOWN": 9.0},
        portfolio,
        suspended={"HALT"},
        prev_closes={"UP": 10.0, "DOWN": 10.0},
    )
    by_symbol = {order.symbol: order for order in result.orders}

    assert by_symbol["HALT"].reason == "not_buyable"
    assert by_symbol["UP"].reason == "not_buyable"
    assert by_symbol["DOWN"].reason == "not_sellable"


def test_research_engine_records_daily_equity_and_report(
    tmp_path: Path,
    seeded_provider: DataProvider,
) -> None:
    pipeline = FactorPipeline()
    universe_filter = UniverseFilter(UniverseConfig(min_history_days=1))
    strategy = MultiFactorTargetStrategy(
        universe_filter,
        pipeline,
        MultiFactorStrategyConfig(n_holdings=5, max_weight=0.1),
    )
    engine = ResearchEngine(
        seeded_provider,
        strategy,
        PaperBroker(PaperBrokerConfig(commission_rate=0, min_commission=0, stamp_tax=0, slippage_bps=0)),
        Portfolio(initial_cash=1_000_000.0),
        pipeline,
    )
    result = engine.run("2020-04-01", "2020-06-30")
    days = seeded_provider.trading_days("2020-04-01", "2020-06-30")
    assert len(result.equity_curve) == len(days)
    assert result.orders

    out = write_research_report(
        result,
        tmp_path / "report",
        "Test",
        assumptions={"demo": True},
        evidence={"data_audit_status": "PASS", "run_manifest_cache_sha256": "abc123"},
    )
    for name in [
        "summary.json",
        "positions.csv",
        "orders.csv",
        "trades.csv",
        "equity.csv",
        "factor_ic.csv",
        "turnover.csv",
        "drawdown.png",
        "html_report.html",
    ]:
        assert (out / name).exists()
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    html = (out / "html_report.html").read_text(encoding="utf-8")
    assert summary["evidence"]["data_audit_status"] == "PASS"
    assert "Data Evidence" in html


class _FixedUniverse:
    def __init__(self, symbols: list[str]) -> None:
        self._symbols = symbols

    def symbols(self, as_of: str, data) -> list[str]:
        del as_of, data
        return list(self._symbols)


class _FixedPipeline:
    def __init__(self, symbols: list[str]) -> None:
        self._symbols = symbols

    def composite_scores(self, as_of: str, universe: list[str], data) -> pd.DataFrame:
        del universe, data
        return pd.DataFrame(
            {
                "date": [as_of] * len(self._symbols),
                "symbol": self._symbols,
                "score": list(reversed(range(1, len(self._symbols) + 1))),
            }
        )


class _DatedPipeline:
    def __init__(self, scores_by_date: dict[str, dict[str, float]]) -> None:
        self._scores_by_date = scores_by_date
        self.calls: list[str] = []

    def composite_scores(self, as_of: str, universe: list[str], data) -> pd.DataFrame:
        del data
        self.calls.append(as_of)
        scores = self._scores_by_date.get(as_of, {})
        frame = pd.DataFrame(
            {
                "date": [as_of] * len(universe),
                "symbol": universe,
                "score": [scores.get(symbol) for symbol in universe],
            }
        ).dropna()
        return frame.sort_values("score", ascending=False).reset_index(drop=True)


class _StaticData:
    def __init__(
        self,
        prices: dict[str, float],
        *,
        trading_days: list[str] | None = None,
    ) -> None:
        self._prices = prices
        self._trading_days = trading_days or []

    def latest_prices(self, symbols: list[str], as_of: str) -> dict[str, float]:
        del as_of
        return {symbol: self._prices[symbol] for symbol in symbols if symbol in self._prices}

    def trading_days(self, start: str, end: str) -> list[str]:
        return [day for day in self._trading_days if start <= day <= end]


def _save_universe_bars(storage: BarStorage, symbol_dates: dict[str, list[str]]) -> None:
    rows = []
    for symbol, dates in symbol_dates.items():
        for day in dates:
            rows.append(
                {
                    "symbol": symbol,
                    "date": day,
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 1_000.0,
                    "amount": 10_000.0,
                }
            )
    storage.save_bars(pd.DataFrame(rows))
