from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.research.candidates import default_candidate_specs
from quantify.research.candidates import CandidateSpec
from quantify.research.demo_data import seed_demo_data
from quantify.research.factors import LowVolatilityFactor, MomentumFactor
from quantify.research.regime_validation import (
    run_candidate_regime_validation,
    write_candidate_regime_validation_report,
)
from quantify.utils.config import Config


def test_candidate_regime_validation_writes_regime_buckets(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "research.db")
    seed_demo_data(storage, "2020-01-01", "2020-12-31")
    specs = [
        CandidateSpec(
            name="momentum_test",
            description="test",
            factors=[MomentumFactor()],
            n_holdings=5,
            max_weight=0.10,
            rebalance="monthly",
        ),
        CandidateSpec(
            name="low_vol_test",
            description="test",
            factors=[LowVolatilityFactor()],
            n_holdings=5,
            max_weight=0.10,
            rebalance="monthly",
        ),
    ]

    report = run_candidate_regime_validation(
        DataProvider(storage),
        _cfg(tmp_path / "research.db"),
        train_days=40,
        test_days=30,
        step_days=30,
        specs=specs,
    )
    out = write_candidate_regime_validation_report(report, tmp_path / "out")

    assert report.candidate_count == 2
    assert report.window_count >= 3
    assert report.summaries
    assert report.buckets
    assert (out / "candidate_regime_validation_report.json").exists()
    assert "Candidate Regime Validation" in (
        out / "candidate_regime_validation_report.md"
    ).read_text(encoding="utf-8")


def test_candidate_regime_validation_cli_writes_outputs(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-12-31")
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(cache), encoding="utf-8")
    out = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_regime_validation.py",
            "--config",
            str(cfg_path),
            "--output-dir",
            str(out),
            "--train-days",
            "40",
            "--test-days",
            "30",
            "--step-days",
            "30",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert (out / "candidate_regime_validation_report.json").exists()


def test_candidate_regime_validation_cli_filters_candidate(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-12-31")
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(cache), encoding="utf-8")
    out = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_regime_validation.py",
            "--config",
            str(cfg_path),
            "--output-dir",
            str(out),
            "--train-days",
            "40",
            "--test-days",
            "30",
            "--step-days",
            "30",
            "--candidate",
            "price_volume_defensive",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((out / "candidate_regime_validation_report.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["candidate_count"] == 1
    assert {summary["candidate"] for summary in payload["summaries"]} == {"price_volume_defensive"}


def test_candidate_regime_validation_regime_pause_sees_adverse_windows(tmp_path: Path) -> None:
    cache = tmp_path / "weak.db"
    storage = BarStorage(cache)
    _seed_weak_market_data(storage)
    cfg = _cfg(cache)
    spec = next(item for item in default_candidate_specs(cfg) if item.name == "regime_pause_price_volume")

    report = run_candidate_regime_validation(
        DataProvider(storage),
        cfg,
        train_days=40,
        test_days=30,
        step_days=30,
        specs=[spec],
    )

    assert report.windows
    assert any(window.regime_label != "unknown" for window in report.windows)
    assert report.summaries[0].candidate == "regime_pause_price_volume"


def _cfg(cache_path: Path) -> Config:
    return Config(
        {
            "research": {
                "start": "2020-01-01",
                "end": "2020-12-31",
                "initial_cash": 1_000_000.0,
                "rebalance": "monthly",
                "allow_demo_data": True,
            },
            "data": {"cache_path": str(cache_path)},
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
            "risk": {"max_drawdown_stop": 0.2},
        }
    )


def _cfg_yaml(cache_path: Path) -> str:
    return f"""
research:
  start: "2020-01-01"
  end: "2020-12-31"
  initial_cash: 1000000.0
  rebalance: monthly
  allow_demo_data: true
data:
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
