from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.readiness import build_manual_target_plan, write_manual_target_plan
from quantify.research.demo_data import seed_demo_data
from quantify.utils.config import Config
from quantify.research.candidates import default_candidate_specs


def test_manual_target_plan_writes_manual_only_files(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-12-31")
    current = pd.DataFrame({"date": ["2020-12-31"], "symbol": ["DEMO001"], "quantity": [100]})

    plan = build_manual_target_plan(
        DataProvider(storage),
        _cfg(cache),
        as_of="2020-12-31",
        capital=100_000,
        cash_buffer_pct=0.10,
        current_positions=current,
    )
    out = write_manual_target_plan(plan, tmp_path / "out")
    manual = pd.read_csv(out / "manual_trade_sheet.csv")

    assert plan.target_count > 0
    assert plan.estimated_gross_exposure <= plan.capital
    assert (out / "target_portfolio.json").exists()
    assert (out / "target_portfolio.csv").exists()
    assert "avg_amount_20d" in manual.columns
    assert "risk_flags" in manual.columns
    assert set(manual["instruction"]) == {"MANUAL_REFERENCE_ONLY_NO_BROKER_ORDER"}


def test_manual_target_plan_warns_on_low_liquidity_and_industry_concentration(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-12-31")
    symbols = storage.load_all_bars_from_db_symbols()
    storage.save_stock_info(pd.DataFrame({"symbol": symbols, "name": symbols, "industry": ["same"] * len(symbols)}))
    bars = storage.load_all_bars(symbols)
    bars["amount"] = 1.0
    storage.save_bars(bars)

    plan = build_manual_target_plan(
        DataProvider(storage),
        _cfg(cache),
        as_of="2020-12-31",
        capital=100_000,
        cash_buffer_pct=0.01,
    )

    assert any("low or missing 20-day average amount" in warning for warning in plan.warnings)
    assert any("Cash buffer is below 3%" in warning for warning in plan.warnings)
    assert any("Top industry" in warning for warning in plan.warnings)


def test_manual_target_plan_flags_current_positions_with_tradability_risks(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-12-31")
    info = storage.load_stock_info()
    info.loc[info["symbol"] == "DEMO001", ["name", "delist_date", "is_st"]] = [
        "ST demo risk",
        "2020-12-31",
        1,
    ]
    storage.save_stock_info(info)
    storage.save_suspensions(pd.DataFrame({"date": ["2020-12-31"], "symbol": ["DEMO001"]}))
    _force_last_two_closes(storage, "DEMO001", previous=10.0, latest=11.0)
    _force_last_two_closes(storage, "DEMO002", previous=10.0, latest=9.0)
    current = pd.DataFrame(
        {
            "date": ["2020-12-31", "2020-12-31"],
            "symbol": ["DEMO001", "DEMO002"],
            "quantity": [100, 100],
        }
    )

    plan = build_manual_target_plan(
        DataProvider(storage),
        _cfg(cache),
        as_of="2020-12-31",
        capital=100_000,
        current_positions=current,
    )
    by_symbol = {row.symbol: row for row in plan.rows}

    assert {"ST", "DELISTED", "SUSPENDED", "LIMIT_UP"}.issubset(set(by_symbol["DEMO001"].risk_flags.split(";")))
    assert "LIMIT_DOWN" in by_symbol["DEMO002"].risk_flags.split(";")
    assert by_symbol["DEMO001"].instruction == "MANUAL_SELL_REVIEW"
    assert any("ST/delisting/suspension/limit-price" in warning for warning in plan.warnings)


def test_manual_target_plan_cli_writes_outputs(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-12-31")
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(cache), encoding="utf-8")
    out = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_target_plan.py",
            "--config",
            str(cfg_path),
            "--output-dir",
            str(out),
            "--as-of",
            "2020-12-31",
            "--capital",
            "100000",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert (out / "target_portfolio.md").exists()
    assert (out / "manual_trade_sheet.csv").exists()


def test_manual_target_plan_warns_for_regime_pause_candidate(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-12-31")

    plan = build_manual_target_plan(
        DataProvider(storage),
        _cfg(cache),
        as_of="2020-12-31",
        candidate="regime_pause_price_volume",
        capital=100_000,
    )

    assert any("explicit pause/resume review notes" in warning for warning in plan.warnings)


def test_manual_target_plan_uses_default_regime_pause_spec(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path / "research.db")
    spec = next(item for item in default_candidate_specs(cfg) if item.name == "regime_pause_price_volume")

    assert spec.trend_gate == "defensive_or_worse"
    assert spec.trend_filter is True
    assert spec.description.startswith("OHLCV-only defensive price-volume basket")


@pytest.mark.parametrize(
    ("capital", "cash_buffer_pct", "message"),
    [
        (0, 0.05, "positive finite"),
        (-100_000, 0.05, "positive finite"),
        (100_000, -0.01, r"\[0, 1\)"),
        (100_000, 1.0, r"\[0, 1\)"),
    ],
)
def test_manual_target_plan_rejects_invalid_capital_inputs(
    tmp_path: Path,
    capital: float,
    cash_buffer_pct: float,
    message: str,
) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-12-31")

    with pytest.raises(ValueError, match=message):
        build_manual_target_plan(
            DataProvider(storage),
            _cfg(cache),
            as_of="2020-12-31",
            capital=capital,
            cash_buffer_pct=cash_buffer_pct,
        )


def _cfg(cache_path: Path) -> Config:
    return Config(
        {
            "research": {
                "start": "2020-01-01",
                "end": "2020-12-31",
                "initial_cash": 100_000.0,
                "rebalance": "monthly",
            },
            "data": {"source": "demo", "cache_path": str(cache_path)},
            "universe": {
                "mode": "all_a",
                "index_code": "000906",
                "include_st": False,
                "min_history_days": 20,
            },
            "strategy": {"n_holdings": 5, "max_weight": 0.10},
            "broker": {
                "commission_rate": 0.0,
                "min_commission": 0.0,
                "stamp_tax": 0.0,
                "slippage_bps": 0.0,
                "price_limit_pct": 0.10,
                "lot_size": 100,
            },
        }
    )


def _force_last_two_closes(storage: BarStorage, symbol: str, *, previous: float, latest: float) -> None:
    bars = storage.load_bars(symbol)
    tail_index = bars.tail(2).index
    bars.loc[tail_index[0], ["open", "high", "low", "close"]] = [previous, previous, previous, previous]
    bars.loc[tail_index[1], ["open", "high", "low", "close"]] = [latest, latest, latest, latest]
    bars.loc[tail_index, "amount"] = bars.loc[tail_index, "volume"] * bars.loc[tail_index, "close"]
    storage.save_bars(bars.loc[tail_index])


def _cfg_yaml(cache_path: Path) -> str:
    return f"""
research:
  start: "2020-01-01"
  end: "2020-12-31"
  initial_cash: 100000.0
  rebalance: monthly
  allow_demo_data: true
data:
  source: demo
  cache_path: "{cache_path.as_posix()}"
universe:
  mode: all_a
  index_code: "000906"
  include_st: false
  min_history_days: 20
strategy:
  n_holdings: 5
  max_weight: 0.10
risk:
  max_drawdown_stop: 0.2
broker:
  commission_rate: 0.0
  min_commission: 0.0
  stamp_tax: 0.0
  slippage_bps: 0.0
  price_limit_pct: 0.10
  lot_size: 100
"""
