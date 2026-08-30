from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.research.demo_data import seed_demo_data
from quantify.research.walk_forward import run_walk_forward, write_walk_forward_report
from quantify.utils.config import Config


def test_walk_forward_writes_multiple_windows(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "research.db")
    seed_demo_data(storage, "2020-01-01", "2020-12-31")
    cfg = _cfg(tmp_path / "research.db")

    report = run_walk_forward(
        DataProvider(storage),
        cfg,
        train_days=40,
        test_days=30,
        step_days=30,
    )
    out = write_walk_forward_report(report, tmp_path / "out")

    assert report.window_count >= 3
    assert report.status in {"PASS", "WATCH", "BLOCK"}
    assert report.selection_safe is True
    assert report.test_used_for_selection is False
    assert report.configuration["mode"] == "expanding"
    assert all(window.fold.selection.end < window.start for window in report.windows)
    assert (out / "walk_forward_report.json").exists()
    assert "Walk-forward Report" in (out / "walk_forward_report.md").read_text(encoding="utf-8")


def test_walk_forward_cli_writes_outputs(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-12-31")
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(cache), encoding="utf-8")
    out = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_walk_forward.py",
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
    assert (out / "walk_forward_report.json").exists()


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
