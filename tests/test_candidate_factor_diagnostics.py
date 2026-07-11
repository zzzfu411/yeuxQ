from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.research.candidate_factor_diagnostics import (
    run_candidate_factor_diagnostics,
    write_candidate_factor_diagnostics_report,
)
from quantify.research.candidates import CandidateSpec
from quantify.research.demo_data import seed_demo_data
from quantify.research.factors import LowVolatilityFactor, MomentumFactor
from quantify.utils.config import Config


def test_candidate_factor_diagnostics_writes_component_report(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "research.db")
    seed_demo_data(storage, "2020-01-01", "2020-12-31")
    specs = [
        CandidateSpec(
            name="two_factor_test",
            description="test",
            factors=[MomentumFactor(), LowVolatilityFactor()],
            n_holdings=5,
            max_weight=0.10,
            rebalance="monthly",
        )
    ]

    report = run_candidate_factor_diagnostics(
        DataProvider(storage),
        _cfg(tmp_path / "research.db"),
        train_days=40,
        test_days=30,
        step_days=30,
        specs=specs,
    )
    out = write_candidate_factor_diagnostics_report(report, tmp_path / "out")

    assert report.candidate_count == 1
    assert report.diagnostics[0].component_count == 2
    assert (out / "candidate_factor_diagnostics.json").exists()
    assert "Candidate Factor Diagnostics" in (out / "candidate_factor_diagnostics.md").read_text(encoding="utf-8")


def test_candidate_factor_diagnostics_marks_component_limited_triage(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "research.db")
    seed_demo_data(storage, "2020-01-01", "2020-12-31")
    specs = [
        CandidateSpec(
            name="two_factor_test",
            description="test",
            factors=[MomentumFactor(), LowVolatilityFactor()],
            n_holdings=5,
            max_weight=0.10,
            rebalance="monthly",
        )
    ]

    report = run_candidate_factor_diagnostics(
        DataProvider(storage),
        _cfg(tmp_path / "research.db"),
        train_days=40,
        test_days=30,
        step_days=30,
        specs=specs,
        max_components=1,
    )
    diagnostic = report.diagnostics[0]

    assert diagnostic.component_count == 1
    assert diagnostic.total_component_count == 2
    assert diagnostic.component_limit == 1
    assert diagnostic.status == "WATCH"
    assert report.status == "WATCH"
    assert any("limited to 1 of 2" in finding for finding in diagnostic.findings)


def test_candidate_factor_diagnostics_cli_writes_outputs(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    seed_demo_data(BarStorage(cache), "2020-01-01", "2020-12-31")
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(cache), encoding="utf-8")
    out = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_factor_diagnostics.py",
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
            "--max-components",
            "1",
            "--candidate",
            "core_multifactor",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert (out / "candidate_factor_diagnostics.json").exists()


def test_candidate_factor_diagnostics_filters_candidate(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "research.db")
    seed_demo_data(storage, "2020-01-01", "2020-12-31")

    report = run_candidate_factor_diagnostics(
        DataProvider(storage),
        _cfg(tmp_path / "research.db"),
        train_days=40,
        test_days=30,
        step_days=30,
        candidate="core_multifactor",
    )

    assert report.candidate_count == 1
    assert report.diagnostics[0].candidate == "core_multifactor"


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
            "data": {"cache_path": str(cache_path), "source": "demo"},
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
