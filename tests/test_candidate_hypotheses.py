from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from quantify.research.candidate_hypotheses import (
    build_candidate_hypothesis_catalog,
    write_candidate_hypothesis_catalog,
)
from quantify.utils.config import Config


def test_candidate_hypothesis_catalog_writes_default_candidates(tmp_path: Path) -> None:
    catalog = build_candidate_hypothesis_catalog(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    out = write_candidate_hypothesis_catalog(catalog, tmp_path / "out")

    payload = json.loads((out / "candidate_hypotheses.json").read_text(encoding="utf-8"))
    markdown = (out / "candidate_hypotheses.md").read_text(encoding="utf-8")

    assert payload["status"] == "RESEARCH_ONLY"
    assert payload["candidate_count"] == 18
    assert {item["name"] for item in payload["candidates"]} == {
        "price_volume_defensive",
        "low_turnover_price_volume",
        "low_turnover_low_concentration_price_volume",
        "trend_filtered_price_volume",
        "trend_filtered_quarterly_price_volume",
        "trend_filtered_quarterly_low_concentration_price_volume",
        "defensive_scaled_quarterly_price_volume",
        "stable_universe_slow_signal_price_volume",
        "long_momentum_liquidity_monthly_price_volume",
        "liquidity_neutral_momentum_guard_price_volume",
        "defensive_cash_guard_price_volume",
        "risk_off_cash_stop_price_volume",
        "regime_pause_price_volume",
        "core_multifactor",
        "defensive_low_vol",
        "momentum_quality",
        "value_low_vol",
        "trend_filtered_core",
    }
    assert all(item["required_validation_gates"] for item in payload["candidates"])
    assert all(item["automatic_downgrade_conditions"] for item in payload["candidates"])
    assert all(item["paper_readiness_requirements"] for item in payload["candidates"])
    ohlcv = next(item for item in payload["candidates"] if item["name"] == "price_volume_defensive")
    assert ohlcv["data_dependency"] == "ohlcv_only"
    assert "value_ep" not in ohlcv["factors"]
    assert "quality_roe" not in ohlcv["factors"]
    assert any("OHLCV-only" in gate for gate in ohlcv["required_validation_gates"])
    low_turnover = next(item for item in payload["candidates"] if item["name"] == "low_turnover_price_volume")
    assert low_turnover["data_dependency"] == "ohlcv_only"
    assert low_turnover["rebalance"] == "quarterly"
    assert any("turnover" in risk.lower() for risk in low_turnover["key_risks"])
    low_turnover_low_conc = next(
        item
        for item in payload["candidates"]
        if item["name"] == "low_turnover_low_concentration_price_volume"
    )
    assert low_turnover_low_conc["data_dependency"] == "ohlcv_only"
    assert low_turnover_low_conc["rebalance"] == "quarterly"
    assert low_turnover_low_conc["max_weight"] == 0.0245
    assert any("low-turnover" in gate.lower() or "drawdown" in gate.lower() for gate in low_turnover_low_conc["required_validation_gates"])
    filtered = next(item for item in payload["candidates"] if item["name"] == "trend_filtered_price_volume")
    assert filtered["data_dependency"] == "ohlcv_only"
    assert filtered["trend_filter"] is True
    assert any("cash drag" in risk.lower() for risk in filtered["key_risks"])
    filtered_quarterly = next(
        item
        for item in payload["candidates"]
        if item["name"] == "trend_filtered_quarterly_price_volume"
    )
    assert filtered_quarterly["data_dependency"] == "ohlcv_only"
    assert filtered_quarterly["trend_filter"] is True
    assert filtered_quarterly["rebalance"] == "quarterly"
    assert any("quarterly" in gate.lower() for gate in filtered_quarterly["required_validation_gates"])
    filtered_quarterly_low_conc = next(
        item
        for item in payload["candidates"]
        if item["name"] == "trend_filtered_quarterly_low_concentration_price_volume"
    )
    assert filtered_quarterly_low_conc["data_dependency"] == "ohlcv_only"
    assert filtered_quarterly_low_conc["trend_filter"] is True
    assert filtered_quarterly_low_conc["rebalance"] == "quarterly"
    assert filtered_quarterly_low_conc["max_weight"] == 0.0245
    assert any(
        "lower concentration" in gate.lower() or "drawdown" in gate.lower()
        for gate in filtered_quarterly_low_conc["required_validation_gates"]
    )
    defensive_scaled = next(
        item
        for item in payload["candidates"]
        if item["name"] == "defensive_scaled_quarterly_price_volume"
    )
    assert defensive_scaled["data_dependency"] == "ohlcv_only"
    assert defensive_scaled["trend_filter"] is True
    assert defensive_scaled["trend_scale"] == 0.15
    assert defensive_scaled["trend_gate"] == "defensive_or_worse"
    assert defensive_scaled["rebalance"] == "quarterly"
    assert defensive_scaled["max_weight"] == 0.03
    assert any("defensive" in gate.lower() for gate in defensive_scaled["required_validation_gates"])
    slow_signal = next(
        item
        for item in payload["candidates"]
        if item["name"] == "stable_universe_slow_signal_price_volume"
    )
    assert slow_signal["data_dependency"] == "ohlcv_only"
    assert slow_signal["trend_filter"] is False
    assert slow_signal["rebalance"] == "quarterly"
    assert slow_signal["max_weight"] == 0.02
    assert "long_momentum_120d_skip20d" in slow_signal["factors"]
    assert "momentum_20d" not in slow_signal["factors"]
    assert any("maintenance turnover" in gate.lower() for gate in slow_signal["required_validation_gates"])
    assert any("stale-position" in item.lower() for item in slow_signal["paper_readiness_requirements"])
    long_momentum_liquidity = next(
        item
        for item in payload["candidates"]
        if item["name"] == "long_momentum_liquidity_monthly_price_volume"
    )
    assert long_momentum_liquidity["data_dependency"] == "ohlcv_only"
    assert long_momentum_liquidity["trend_filter"] is False
    assert long_momentum_liquidity["rebalance"] == "monthly"
    assert long_momentum_liquidity["max_weight"] == 0.02
    assert "long_momentum_120d_skip20d" in long_momentum_liquidity["factors"]
    assert "liquidity_amount_20d" in long_momentum_liquidity["factors"]
    assert "value_ep" not in long_momentum_liquidity["factors"]
    assert "quality_roe" not in long_momentum_liquidity["factors"]
    assert "momentum_20d" not in long_momentum_liquidity["factors"]
    assert any("factor diagnostics" in gate.lower() for gate in long_momentum_liquidity["required_validation_gates"])
    assert any("momentum/liquidity concentration" in item.lower() for item in long_momentum_liquidity["paper_readiness_requirements"])
    liquidity_neutral_guard = next(
        item
        for item in payload["candidates"]
        if item["name"] == "liquidity_neutral_momentum_guard_price_volume"
    )
    assert liquidity_neutral_guard["data_dependency"] == "ohlcv_only"
    assert liquidity_neutral_guard["trend_filter"] is True
    assert liquidity_neutral_guard["trend_scale"] == 0.15
    assert liquidity_neutral_guard["trend_gate"] == "defensive_or_worse"
    assert liquidity_neutral_guard["rebalance"] == "quarterly"
    assert liquidity_neutral_guard["max_weight"] == 0.015
    assert "liquidity_neutral_long_momentum_120d_skip20d" in liquidity_neutral_guard["factors"]
    assert "low_volatility_120d" in liquidity_neutral_guard["factors"]
    assert "liquidity_amount_20d" not in liquidity_neutral_guard["factors"]
    assert "value_ep" not in liquidity_neutral_guard["factors"]
    assert "quality_roe" not in liquidity_neutral_guard["factors"]
    assert any("liquidity-neutral" in gate.lower() for gate in liquidity_neutral_guard["required_validation_gates"])
    assert any("defensive-gate" in item.lower() for item in liquidity_neutral_guard["paper_readiness_requirements"])
    cash_guard = next(
        item for item in payload["candidates"] if item["name"] == "defensive_cash_guard_price_volume"
    )
    assert cash_guard["data_dependency"] == "ohlcv_only"
    assert cash_guard["trend_filter"] is True
    assert cash_guard["trend_scale"] == 0.15
    assert cash_guard["rebalance"] == "quarterly"
    assert any("cash guard" in risk.lower() or "cash drag" in risk.lower() for risk in cash_guard["key_risks"])
    cash_stop = next(
        item for item in payload["candidates"] if item["name"] == "risk_off_cash_stop_price_volume"
    )
    assert cash_stop["data_dependency"] == "ohlcv_only"
    assert cash_stop["trend_filter"] is True
    assert cash_stop["trend_scale"] == 0.0
    assert any(
        "cash-stop" in gate.lower()
        for gate in cash_stop["required_validation_gates"]
    )
    regime_pause = next(
        item for item in payload["candidates"] if item["name"] == "regime_pause_price_volume"
    )
    assert regime_pause["data_dependency"] == "ohlcv_only"
    assert regime_pause["trend_filter"] is True
    assert regime_pause["trend_scale"] == 0.0
    assert any("explicit regime pause" in regime for regime in regime_pause["intended_regimes"])
    assert any("generic broad-trend tweak" in item.lower() for item in regime_pause["automatic_downgrade_conditions"])
    assert "not a live trading instruction" in markdown
    assert "Do not connect hypothesis output to a real broker." in markdown


def test_candidate_hypothesis_cli_writes_outputs(tmp_path: Path) -> None:
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(tmp_path / "research.db"), encoding="utf-8")
    out = tmp_path / "hypotheses"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/write_candidate_hypotheses.py",
            "--config",
            str(cfg_path),
            "--output-dir",
            str(out),
            "--as-of",
            "2026-06-08",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = json.loads((out / "candidate_hypotheses.json").read_text(encoding="utf-8"))
    assert payload["as_of"] == "2026-06-08"
    assert (out / "candidate_hypotheses.md").exists()


def _cfg(cache_path: Path) -> Config:
    return Config(
        {
            "research": {
                "start": "2024-01-02",
                "end": "2024-01-03",
                "initial_cash": 1_000_000.0,
                "rebalance": "monthly",
            },
            "universe": {
                "mode": "all_a",
                "index_code": "000906",
                "include_st": False,
                "min_history_days": 1,
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
            "data": {"cache_path": str(cache_path), "source": "csv"},
            "output": {"results_dir": str(cache_path.parent)},
        }
    )


def _cfg_yaml(cache_path: Path) -> str:
    return f"""
research:
  start: "2024-01-02"
  end: "2024-01-03"
  in_sample_end: "2024-01-02"
  out_sample_start: "2024-01-03"
  initial_cash: 1000000.0
  rebalance: monthly
  allow_demo_data: false
data:
  source: csv
  cache_path: "{cache_path.as_posix()}"
  adjust: qfq
universe:
  mode: all_a
  index_code: "000906"
  include_st: false
  min_history_days: 1
strategy:
  name: multi_factor
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
output:
  results_dir: "{cache_path.parent.as_posix()}"
"""
