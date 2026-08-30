from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.research.candidate_stress_matrix import (
    CandidateStressScenario,
    default_candidate_stress_scenarios,
    run_candidate_stress_matrix,
    select_candidate_stress_scenarios,
    write_candidate_stress_matrix_report,
)
from quantify.research.candidates import default_candidate_specs
from quantify.research.demo_data import seed_demo_data
from quantify.utils.config import Config


def test_candidate_stress_matrix_keeps_research_only_boundaries(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    seed_demo_data(BarStorage(cache), "2020-01-01", "2020-12-31")
    cfg = _cfg(cache)
    spec = next(item for item in default_candidate_specs(cfg) if item.name == "price_volume_defensive")
    report = run_candidate_stress_matrix(
        DataProvider(BarStorage(cache)),
        cfg,
        specs=[spec],
        scenarios_by_candidate={
            spec.name: [
                CandidateStressScenario(
                    name="baseline",
                    n_holdings=spec.n_holdings,
                    max_weight=spec.max_weight,
                    rebalance=spec.rebalance,
                )
            ]
        },
    )
    out = write_candidate_stress_matrix_report(report, tmp_path / "out")
    payload = json.loads((out / "candidate_stress_matrix.json").read_text(encoding="utf-8"))

    assert payload["status"] == "RESEARCH_ONLY"
    assert payload["promotion_decision"] == "BLOCK"
    assert payload["can_satisfy_launch_gate"] is False
    assert payload["can_enter_paper"] is False
    assert payload["can_enter_micro_live_ready"] is False
    assert payload["can_generate_broker_orders"] is False
    assert payload["candidate_count"] == 1
    assert payload["scenario_count"] == 1
    assert payload["results"][0]["candidate"] == "price_volume_defensive"
    assert (out / "candidate_stress_matrix.md").exists()
    assert (out / "candidate_stress_matrix.csv").exists()


def test_candidate_stress_scenarios_include_trend_ablation(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path / "research.db")
    spec = next(
        item for item in default_candidate_specs(cfg) if item.name == "trend_filtered_price_volume"
    )
    scenarios = default_candidate_stress_scenarios(spec)
    names = {scenario.name for scenario in scenarios}
    selected = select_candidate_stress_scenarios(spec, ["baseline", "trend_filter_off"])

    assert "trend_filter_off" in names
    assert "trend_filter_stronger" in names
    assert [scenario.name for scenario in selected] == ["baseline", "trend_filter_off"]


def test_candidate_stress_scenarios_include_turnover_control(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path / "research.db")
    spec = next(
        item for item in default_candidate_specs(cfg) if item.name == "defensive_scaled_quarterly_price_volume"
    )
    selected = select_candidate_stress_scenarios(
        spec,
        ["turnover_control", "stability_control", "score_smoothing"],
    )

    assert selected[0].name == "turnover_control"
    assert selected[0].hold_rank_buffer >= 5
    assert selected[0].min_trade_weight == 0.01
    assert selected[1].name == "stability_control"
    assert selected[1].hold_rank_buffer >= spec.n_holdings
    assert selected[1].min_trade_weight == 0.02
    assert selected[1].max_new_positions == max(1, int(spec.n_holdings * 0.20))
    assert selected[2].name == "score_smoothing"
    assert selected[2].score_smoothing_observations == 3
    assert selected[2].score_smoothing_step_days == 20


def test_candidate_stress_scenarios_force_small_capital_cost_assumptions(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path / "research.db")
    spec = next(
        item for item in default_candidate_specs(cfg) if item.name == "price_volume_defensive"
    )
    scenarios = {
        scenario.name: scenario for scenario in default_candidate_stress_scenarios(spec)
    }

    for slippage_bps in (5, 10, 20):
        scenario = scenarios[f"small_capital_{slippage_bps}bps"]
        assert scenario.initial_cash == 100_000
        assert scenario.lot_size == 100
        assert scenario.min_commission == 5
        assert scenario.stamp_tax == 0.0005
        assert scenario.slippage_bps == slippage_bps


def test_small_capital_stress_uses_effective_execution_assumptions(tmp_path: Path) -> None:
    cache = tmp_path / "small-capital.db"
    seed_demo_data(BarStorage(cache), "2020-01-01", "2020-12-31")
    cfg = _cfg(cache)
    spec = next(
        item for item in default_candidate_specs(cfg) if item.name == "price_volume_defensive"
    )
    scenario = select_candidate_stress_scenarios(spec, ["small_capital_20bps"])[0]

    result = run_candidate_stress_matrix(
        DataProvider(BarStorage(cache)),
        cfg,
        specs=[spec],
        scenarios_by_candidate={spec.name: [scenario]},
    ).results[0]

    assert result.execution_initial_cash == 100_000
    assert result.parameters["effective_lot_size"] == 100
    assert result.parameters["effective_min_commission"] == 5
    assert result.parameters["effective_stamp_tax"] == 0.0005
    assert result.parameters["effective_slippage_bps"] == 20
    assert result.min_commission_hit_count > 0
    assert result.below_lot_reject_count > 0


def test_candidate_stress_matrix_cli_filters_candidate_and_scenario(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    seed_demo_data(BarStorage(cache), "2020-01-01", "2020-12-31")
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(cache), encoding="utf-8")
    output_dir = tmp_path / "stress"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_stress_matrix.py",
            "--config",
            str(cfg_path),
            "--output-dir",
            str(output_dir),
            "--candidate",
            "price_volume_defensive",
            "--scenario",
            "baseline",
            "--research-start",
            "2020-03-01",
            "--research-end",
            "2020-06-30",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads((output_dir / "candidate_stress_matrix.json").read_text(encoding="utf-8"))

    assert completed.returncode == 0
    assert payload["candidate_count"] == 1
    assert payload["scenario_count"] == 1
    assert payload["results"][0]["scenario"] == "baseline"
    assert payload["results"][0]["candidate"] == "price_volume_defensive"
    assert "initial_turnover_pct" in payload["results"][0]
    assert "avg_maintenance_turnover_pct" in payload["results"][0]
    assert "max_new_positions" in payload["results"][0]["parameters"]
    assert "score_smoothing_observations" in payload["results"][0]["parameters"]
    assert "max_maintenance_turnover_pct" in payload["summaries"][0]


def test_candidate_research_stress_matrix_cli_runs_without_launch_gate(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "research.db"
    seed_demo_data(BarStorage(cache), "2020-01-01", "2020-12-31")
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(cache, allow_demo_data=False), encoding="utf-8")
    output_dir = tmp_path / "research_stress"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_research_stress_matrix.py",
            "--config",
            str(cfg_path),
            "--output-dir",
            str(output_dir),
            "--candidate",
            "price_volume_defensive",
            "--scenario",
            "baseline",
            "--research-start",
            "2020-03-01",
            "--research-end",
            "2020-06-30",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads((output_dir / "candidate_stress_matrix.json").read_text(encoding="utf-8"))

    assert completed.returncode == 0
    assert payload["status"] == "RESEARCH_ONLY"
    assert payload["promotion_decision"] == "BLOCK"
    assert payload["candidate_count"] == 1
    assert payload["scenario_count"] == 1
    assert payload["can_enter_paper"] is False
    assert payload["can_generate_broker_orders"] is False
    assert not (output_dir / "candidate_experiment_launch.json").exists()


def test_candidate_stress_matrix_regime_pause_can_pause_in_weak_market(tmp_path: Path) -> None:
    cache = tmp_path / "weak.db"
    storage = BarStorage(cache)
    _seed_weak_market_data(storage)
    cfg = _cfg(cache)
    spec = next(item for item in default_candidate_specs(cfg) if item.name == "regime_pause_price_volume")

    report = run_candidate_stress_matrix(
        DataProvider(storage),
        cfg,
        specs=[spec],
        scenarios_by_candidate={
            spec.name: [
                CandidateStressScenario(
                    name="baseline",
                    n_holdings=spec.n_holdings,
                    max_weight=spec.max_weight,
                    rebalance=spec.rebalance,
                    trend_filter=spec.trend_filter,
                    trend_scale=spec.trend_scale,
                    trend_gate=spec.trend_gate,
                )
            ]
        },
    )

    assert report.results
    assert any(result.trend_filter_active_days > 0 for result in report.results)


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
            "data": {"source": "demo", "cache_path": str(cache_path)},
            "universe": {
                "mode": "all_a",
                "index_code": "000906",
                "include_st": False,
                "min_history_days": 20,
            },
            "strategy": {"n_holdings": 5, "max_weight": 0.10},
            "risk": {"max_drawdown_stop": 0.20},
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


def _cfg_yaml(cache_path: Path, *, allow_demo_data: bool = True) -> str:
    allow_demo = "true" if allow_demo_data else "false"
    return f"""
research:
  start: "2020-01-01"
  end: "2020-12-31"
  initial_cash: 1000000.0
  rebalance: monthly
  allow_demo_data: {allow_demo}
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
