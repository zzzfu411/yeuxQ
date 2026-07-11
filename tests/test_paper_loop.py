from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.paper import run_paper_loop
from quantify.research.demo_data import seed_demo_data
from quantify.utils.config import Config


def test_paper_loop_recovers_state_and_appends_new_days(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    state_dir = tmp_path / "paper"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-06-30")
    cfg = _cfg(cache)

    first = run_paper_loop(
        DataProvider(storage),
        cfg,
        state_dir=state_dir,
        start="2020-04-01",
        end="2020-05-15",
        initial_cash=100_000,
    )
    second = run_paper_loop(
        DataProvider(storage),
        cfg,
        state_dir=state_dir,
        start="2020-04-01",
        end="2020-06-30",
        initial_cash=100_000,
    )
    state = json.loads((state_dir / "paper_state.json").read_text(encoding="utf-8"))
    daily = pd.read_csv(state_dir / "paper_daily.csv")

    assert first.state.as_of == "2020-05-15"
    assert second.run_days[0] > "2020-05-15"
    assert state["as_of"] == "2020-06-30"
    assert state["broker_connection"] == "none"
    assert len(daily) == state["observed_days"]
    assert (state_dir / "paper_positions.csv").exists()
    assert (state_dir / "paper_orders.csv").exists()
    assert (state_dir / "paper_daily_review.md").exists()


def test_paper_loop_restores_prior_day_for_t_plus_one_release(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    state_dir = tmp_path / "paper_release"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-01-10")
    cfg = _cfg(cache)
    state_dir.mkdir()
    (state_dir / "paper_state.json").write_text(
        json.dumps(
            {
                "as_of": "2020-01-02",
                "observed_days": 1,
                "candidate": "price_volume_defensive",
                "initial_cash": 100_000,
                "cash": 95_000,
                "last_equity": 100_000,
                "position_count": 1,
                "order_count": 1,
                "rejected_order_count": 0,
                "broker_connection": "none",
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        {
            "date": ["2020-01-02"],
            "symbol": ["DEMO001"],
            "quantity": [500],
            "available_qty": [0],
            "price": [10.0],
            "market_value": [5_000.0],
            "weight": [0.05],
            "avg_cost": [10.0],
        }
    ).to_csv(state_dir / "paper_positions.csv", index=False)
    pd.DataFrame(
        {
            "date": ["2020-01-02"],
            "candidate": ["price_volume_defensive"],
            "cash": [95_000.0],
            "equity": [100_000.0],
            "position_count": [1],
            "rebalanced": [True],
            "order_count": [1],
            "rejected_order_count": [0],
            "broker_connection": ["none"],
        }
    ).to_csv(state_dir / "paper_daily.csv", index=False)

    run_paper_loop(
        DataProvider(storage),
        cfg,
        state_dir=state_dir,
        start="2020-01-02",
        end="2020-01-03",
        initial_cash=100_000,
    )
    positions = pd.read_csv(state_dir / "paper_positions.csv")

    restored = positions.loc[positions["symbol"] == "DEMO001"].iloc[0]
    assert int(restored["quantity"]) == 500
    assert int(restored["available_qty"]) == 500


def test_paper_loop_segmented_run_matches_continuous_run(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-06-30")
    cfg = _cfg(cache)
    provider = DataProvider(storage)
    continuous_dir = tmp_path / "paper_continuous"
    segmented_dir = tmp_path / "paper_segmented"

    run_paper_loop(
        provider,
        cfg,
        state_dir=continuous_dir,
        start="2020-04-01",
        end="2020-06-30",
        initial_cash=100_000,
    )
    run_paper_loop(
        provider,
        cfg,
        state_dir=segmented_dir,
        start="2020-04-01",
        end="2020-05-15",
        initial_cash=100_000,
    )
    run_paper_loop(
        provider,
        cfg,
        state_dir=segmented_dir,
        start="2020-04-01",
        end="2020-06-30",
        initial_cash=100_000,
    )

    continuous_state = json.loads((continuous_dir / "paper_state.json").read_text(encoding="utf-8"))
    segmented_state = json.loads((segmented_dir / "paper_state.json").read_text(encoding="utf-8"))
    assert _state_core(segmented_state) == _state_core(continuous_state)
    pd.testing.assert_frame_equal(
        _canonical_frame(segmented_dir / "paper_positions.csv"),
        _canonical_frame(continuous_dir / "paper_positions.csv"),
    )
    pd.testing.assert_frame_equal(
        _canonical_frame(segmented_dir / "paper_orders.csv"),
        _canonical_frame(continuous_dir / "paper_orders.csv"),
    )


def test_paper_loop_rejects_candidate_switch_in_same_state_dir(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-06-30")
    cfg = _cfg(cache)
    state_dir = tmp_path / "paper_candidate_lock"

    run_paper_loop(
        DataProvider(storage),
        cfg,
        state_dir=state_dir,
        start="2020-04-01",
        end="2020-05-15",
        candidate="price_volume_defensive",
        initial_cash=100_000,
    )

    with pytest.raises(ValueError, match="separate state_dir"):
        run_paper_loop(
            DataProvider(storage),
            cfg,
            state_dir=state_dir,
            start="2020-04-01",
            end="2020-06-30",
            candidate="core_multifactor",
            initial_cash=100_000,
        )


def test_paper_loop_cli_writes_outputs(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-06-30")
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(cache), encoding="utf-8")
    state_dir = tmp_path / "paper_cli"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_paper_loop.py",
            "--config",
            str(cfg_path),
            "--state-dir",
            str(state_dir),
            "--start",
            "2020-04-01",
            "--end",
            "2020-06-30",
            "--initial-cash",
            "100000",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert (state_dir / "paper_state.json").exists()
    assert (state_dir / "paper_daily_review.json").exists()
    assert (state_dir / "paper_loop_run.json").exists()
    assert (state_dir / "paper_stability.json").exists()


def test_paper_loop_adds_regime_pause_manual_question(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    state_dir = tmp_path / "paper_regime_pause"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-06-30")
    cfg = _cfg(cache)

    run_paper_loop(
        DataProvider(storage),
        cfg,
        state_dir=state_dir,
        start="2020-04-01",
        end="2020-06-30",
        candidate="regime_pause_price_volume",
        initial_cash=100_000,
    )
    review = json.loads((state_dir / "paper_daily_review.json").read_text(encoding="utf-8"))

    assert any("regime pause or resume" in item.lower() for item in review["manual_review_questions"])


def test_paper_loop_regime_pause_reduces_targets_under_detected_defensive_market(tmp_path: Path) -> None:
    cache = tmp_path / "weak_regime.db"
    state_dir = tmp_path / "paper_regime_runtime"
    storage = BarStorage(cache)
    _seed_weak_market_data(storage)
    cfg = _cfg(cache)

    run_paper_loop(
        DataProvider(storage),
        cfg,
        state_dir=state_dir,
        start="2020-08-03",
        end="2020-12-31",
        candidate="regime_pause_price_volume",
        initial_cash=100_000,
    )
    daily = pd.read_csv(state_dir / "paper_daily.csv")

    rebalanced = daily[daily["rebalanced"] == True]  # noqa: E712
    assert not rebalanced.empty
    assert float(rebalanced["target_weight_sum"].min()) == 0.0


def _cfg(cache_path: Path) -> Config:
    return Config(
        {
            "research": {
                "start": "2020-04-01",
                "end": "2020-06-30",
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


def _cfg_yaml(cache_path: Path) -> str:
    return f"""
research:
  start: "2020-04-01"
  end: "2020-06-30"
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


def _state_core(payload: dict) -> dict:
    keys = [
        "as_of",
        "observed_days",
        "candidate",
        "cash",
        "last_equity",
        "position_count",
        "order_count",
        "rejected_order_count",
        "broker_connection",
    ]
    return {
        key: round(float(payload[key]), 6) if key in {"cash", "last_equity"} else payload[key]
        for key in keys
    }


def _canonical_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    sort_cols = [column for column in ["timestamp", "date", "symbol", "direction"] if column in frame]
    if sort_cols:
        frame = frame.sort_values(sort_cols).reset_index(drop=True)
    for column in frame.select_dtypes(include=["float"]).columns:
        frame[column] = frame[column].round(6)
    return frame


def _seed_weak_market_data(storage: BarStorage) -> None:
    symbols = [f"600{i:03d}" for i in range(1, 9)]
    dates = pd.bdate_range("2020-01-01", "2020-12-31")
    storage.save_calendar(dates)
    storage.save_stock_info(
        pd.DataFrame(
            {
                "symbol": symbols,
                "name": [f"weak_{i}" for i, _symbol in enumerate(symbols, start=1)],
                "exchange": ["SSE"] * len(symbols),
                "list_date": ["2015-01-01"] * len(symbols),
                "delist_date": [""] * len(symbols),
                "industry": ["test"] * len(symbols),
                "is_st": [0] * len(symbols),
            }
        )
    )
    frames = []
    for idx, symbol in enumerate(symbols, start=1):
        steps = pd.Series(range(len(dates)), dtype=float)
        close = (30.0 + idx) * (1 - 0.0012 * steps).clip(lower=0.35)
        volume = 1_000_000 + idx * 10_000
        frames.append(
            pd.DataFrame(
                {
                    "symbol": symbol,
                    "date": [day.date().isoformat() for day in dates],
                    "open": close * 1.001,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": volume,
                    "amount": close * volume,
                }
            )
        )
    storage.save_bars(pd.concat(frames, ignore_index=True))
