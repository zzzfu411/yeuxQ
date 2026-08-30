from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.research.candidate_walk_forward import (
    run_candidate_walk_forward,
    write_candidate_walk_forward_report,
)
from quantify.research.candidates import CandidateSpec
from quantify.research.candidates import default_candidate_specs
from quantify.research.demo_data import seed_demo_data
from quantify.research.factors import LowVolatilityFactor, MomentumFactor
from quantify.utils.config import Config


def test_candidate_walk_forward_compares_candidates(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "research.db")
    seed_demo_data(storage, "2020-01-01", "2020-12-31")
    cfg = _cfg(tmp_path / "research.db")
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

    report = run_candidate_walk_forward(
        DataProvider(storage),
        cfg,
        train_days=40,
        test_days=30,
        step_days=30,
        specs=specs,
    )
    out = write_candidate_walk_forward_report(report, tmp_path / "out")

    assert report.candidate_count == 2
    assert report.window_count >= 3
    assert report.best_candidate in {"momentum_test", "low_vol_test"}
    assert report.selection_safe is True
    assert report.test_used_for_selection is False
    assert len(report.windows) == report.window_count
    assert all(window.selection_rank == 1 for window in report.windows)
    assert all(0.0 <= summary.positive_return_ratio <= 1.0 for summary in report.summaries)
    assert all(isinstance(summary.worst_total_return, float) for summary in report.summaries)
    assert all(summary.worst_max_drawdown >= 0.0 for summary in report.summaries)
    assert (out / "candidate_walk_forward_report.json").exists()
    markdown = (out / "candidate_walk_forward_report.md").read_text(encoding="utf-8")
    payload = json.loads((out / "candidate_walk_forward_report.json").read_text(encoding="utf-8"))
    assert "Candidate Walk-forward" in markdown
    assert "worst_return" in markdown
    assert "trend_filter_days" in markdown
    assert "positive_return_ratio" in payload["summaries"][0]
    assert "worst_total_return" in payload["summaries"][0]
    assert "worst_max_drawdown" in payload["summaries"][0]
    assert "trend_filter_active_days" in payload["summaries"][0]
    assert "trend_filter_active_days" in payload["windows"][0]
    assert payload["selection_protocol"] == "quantify.walk-forward-selection.v2"
    assert payload["test_used_for_selection"] is False
    assert payload["selections"]


def test_candidate_walk_forward_cli_writes_outputs(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-12-31")
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(cache), encoding="utf-8")
    out = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_walk_forward.py",
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
    assert (out / "candidate_walk_forward_report.json").exists()


def test_candidate_walk_forward_cli_filters_candidate(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-12-31")
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(cache), encoding="utf-8")
    out = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_walk_forward.py",
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

    payload = json.loads((out / "candidate_walk_forward_report.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["candidate_count"] == 1
    assert {summary["candidate"] for summary in payload["summaries"]} == {"price_volume_defensive"}


def test_candidate_walk_forward_can_limit_to_recent_windows(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "research.db")
    seed_demo_data(storage, "2020-01-01", "2020-12-31")

    full = run_candidate_walk_forward(
        DataProvider(storage),
        _cfg(tmp_path / "research.db"),
        train_days=40,
        test_days=30,
        step_days=30,
        specs=[
            CandidateSpec(
                name="low_vol_test",
                description="test",
                factors=[LowVolatilityFactor()],
                n_holdings=5,
                max_weight=0.10,
                rebalance="monthly",
            )
        ],
    )
    limited = run_candidate_walk_forward(
        DataProvider(storage),
        _cfg(tmp_path / "research.db"),
        train_days=40,
        test_days=30,
        step_days=30,
        max_windows=2,
        specs=[
            CandidateSpec(
                name="low_vol_test",
                description="test",
                factors=[LowVolatilityFactor()],
                n_holdings=5,
                max_weight=0.10,
                rebalance="monthly",
            )
        ],
    )

    assert full.window_count > 2
    assert limited.window_count == 2
    assert [window.start for window in limited.windows] == [window.start for window in full.windows[-2:]]
    assert any("limited to the latest 2" in warning for warning in limited.warnings)


def test_candidate_walk_forward_applies_regime_pause_runtime_gate(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "weak.db")
    _seed_weak_market_data(storage)
    cfg = _cfg(tmp_path / "weak.db")
    spec = next(item for item in default_candidate_specs(cfg) if item.name == "regime_pause_price_volume")

    report = run_candidate_walk_forward(
        DataProvider(storage),
        cfg,
        train_days=40,
        test_days=30,
        step_days=30,
        specs=[spec],
    )

    assert report.windows
    assert any(window.trend_filter_active_days > 0 for window in report.windows)


def test_candidate_walk_forward_cli_requires_gate_for_real_config(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-12-31")
    cfg_path = tmp_path / "research_recent.yaml"
    cfg_path.write_text(_cfg_yaml(cache).replace("allow_demo_data: true", "allow_demo_data: false"), encoding="utf-8")
    out = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_walk_forward.py",
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

    assert completed.returncode == 2
    assert not (out / "candidate_walk_forward_report.json").exists()
    assert "--gate-report-dir" in completed.stderr


def test_candidate_walk_forward_cli_accepts_pass_launch_gate(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-12-31")
    cfg_path = tmp_path / "research_recent.yaml"
    cfg_path.write_text(_cfg_yaml(cache).replace("allow_demo_data: true", "allow_demo_data: false"), encoding="utf-8")
    out = tmp_path / "out"
    gate = tmp_path / "gate"
    experiment_dir = out
    gate.mkdir()
    (gate / "candidate_experiment_launch.json").write_text(
        json.dumps(
            {
                "decision": "PASS",
                "selected_candidate": "price_volume_defensive",
                "experiment_dir": str(experiment_dir),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_walk_forward.py",
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
            "--gate-report-dir",
            str(gate),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert (out / "candidate_walk_forward_report.json").exists()


def test_candidate_walk_forward_cli_blocks_mismatched_launch_output_dir(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-12-31")
    cfg_path = tmp_path / "research_recent.yaml"
    cfg_path.write_text(_cfg_yaml(cache).replace("allow_demo_data: true", "allow_demo_data: false"), encoding="utf-8")
    out = tmp_path / "wrong_out"
    gate = tmp_path / "gate"
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    gate.mkdir()
    (gate / "candidate_experiment_launch.json").write_text(
        json.dumps(
            {
                "decision": "PASS",
                "selected_candidate": "price_volume_defensive",
                "experiment_dir": str(experiment_dir),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_walk_forward.py",
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
            "--gate-report-dir",
            str(gate),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert not (out / "candidate_walk_forward_report.json").exists()
    assert "output directory must match launch experiment_dir" in completed.stderr


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
