from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.goal import CapitalGoal
from quantify.research import candidates as candidates_module
from quantify.core.portfolio import Portfolio
from quantify.research.candidates import (
    CandidateSpec,
    TrendFilteredTargetStrategy,
    default_candidate_specs,
    run_candidate_selection,
    write_candidate_selection_report,
)
from quantify.research.demo_data import seed_demo_data
from quantify.research.factors import FactorPipeline, LowVolatilityFactor, MomentumFactor
from quantify.research.strategy import MultiFactorStrategyConfig
from quantify.research.universe import UniverseConfig, UniverseFilter
from quantify.utils.config import Config


def test_candidate_selection_runs_and_writes_ranked_report(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "research.db")
    seed_demo_data(storage, "2020-01-01", "2020-06-30")
    provider = DataProvider(storage)
    specs = [
        CandidateSpec(
            name="tiny_core",
            description="test",
            factors=[MomentumFactor(), LowVolatilityFactor()],
            n_holdings=5,
            max_weight=0.10,
            rebalance="monthly",
        )
    ]

    report = run_candidate_selection(
        provider,
        _cfg(tmp_path / "research.db"),
        goal=CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8),
        data_audit_status="PASS",
        robustness_status="PASS",
        specs=specs,
    )
    out = write_candidate_selection_report(report, tmp_path / "out")

    assert report.results
    assert report.execution_initial_cash == 100_000
    assert report.results[0].execution_initial_cash == 100_000
    assert report.results[0].metrics["initial_equity"] == 100_000
    assert report.results[0].below_lot_reject_count > 0
    assert report.best_candidate == ""
    assert report.selected_candidate == ""
    assert report.top_candidate == "tiny_core"
    assert (out / "candidate_selection.json").exists()
    assert (out / "candidate_selection.csv").exists()
    payload = json.loads((out / "candidate_selection.json").read_text(encoding="utf-8"))
    data = pd.read_csv(out / "candidate_selection.csv")
    assert payload["results"][0]["market_regime_status"] == "WATCH"
    assert payload["results"][0]["market_regime_review"]["fit"] == "insufficient_context"
    assert payload["execution_initial_cash"] == 100_000
    assert payload["selected_candidate"] == ""
    assert payload["top_candidate"] == "tiny_core"
    assert data.loc[0, "market_regime_status"] == "WATCH"


def test_candidate_selection_cli_uses_existing_gate_artifacts(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "research.db")
    seed_demo_data(storage, "2020-01-01", "2020-06-30")
    output_dir = tmp_path / "selection"
    output_dir.mkdir()
    (output_dir / "data_audit.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    (output_dir / "robustness_report.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    weekly = output_dir / "weekly"
    weekly.mkdir()
    (weekly / "market_regime.json").write_text(
        json.dumps(_market_regime("neutral", status="PASS", start="2020-04-01", end="2020-06-30")),
        encoding="utf-8",
    )
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(tmp_path / "research.db"), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_selection.py",
            "--config",
            str(cfg_path),
            "--output-dir",
            str(output_dir),
            "--years",
            "8",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert (output_dir / "candidate_selection.md").exists()
    data = pd.read_csv(output_dir / "candidate_selection.csv")
    assert not data.empty
    assert "market_regime_status" in data.columns
    assert set(data["market_regime_status"]) == {"PASS"}
    payload = json.loads((output_dir / "candidate_selection.json").read_text(encoding="utf-8"))
    assert payload["market_regime"]["label"] == "neutral"


def test_candidate_selection_cli_consumes_candidate_regime_validation(
    tmp_path: Path,
) -> None:
    storage = BarStorage(tmp_path / "research.db")
    seed_demo_data(storage, "2020-01-01", "2020-06-30")
    output_dir = tmp_path / "selection"
    output_dir.mkdir()
    (output_dir / "data_audit.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    (output_dir / "robustness_report.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    (output_dir / "market_regime.json").write_text(
        json.dumps(_market_regime("neutral", status="PASS", start="2020-04-01", end="2020-06-30")),
        encoding="utf-8",
    )
    (output_dir / "candidate_regime_validation_report.json").write_text(
        json.dumps(_candidate_regime_validation("price_volume_defensive")),
        encoding="utf-8",
    )
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(tmp_path / "research.db"), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_selection.py",
            "--config",
            str(cfg_path),
            "--output-dir",
            str(output_dir),
            "--years",
            "8",
            "--candidate",
            "price_volume_defensive",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = json.loads((output_dir / "candidate_selection.json").read_text(encoding="utf-8"))
    data = pd.read_csv(output_dir / "candidate_selection.csv")
    assert payload["results"][0]["candidate_regime_validation_status"] == "PASS"
    assert payload["results"][0]["candidate_regime_validation_review"]["known_regime_count"] == 2
    assert data.loc[0, "candidate_regime_validation_status"] == "PASS"
    assert data.loc[0, "candidate_regime_adverse_window_count"] == 1


def test_candidate_selection_cli_filters_candidate(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "research.db")
    seed_demo_data(storage, "2020-01-01", "2020-06-30")
    output_dir = tmp_path / "selection"
    output_dir.mkdir()
    (output_dir / "data_audit.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    (output_dir / "robustness_report.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(tmp_path / "research.db"), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_selection.py",
            "--config",
            str(cfg_path),
            "--output-dir",
            str(output_dir),
            "--years",
            "8",
            "--candidate",
            "price_volume_defensive",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output_dir / "candidate_selection.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert len(payload["results"]) == 1
    assert payload["results"][0]["name"] == "price_volume_defensive"
    assert payload["status"] == "BLOCK"
    assert payload["selected_candidate"] == ""
    assert payload["top_candidate"] == "price_volume_defensive"
    assert payload["results"][0]["capital_goal_fit_status"] == "BLOCK"
    assert "below required path" in "\n".join(
        payload["results"][0]["capital_goal_fit_review"]["findings"]
    )


def test_price_volume_defensive_runs_with_ohlcv_only_data(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "ohlcv.db")
    _seed_ohlcv_only_data(storage)
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = next(item for item in default_candidate_specs(cfg) if item.name == "price_volume_defensive")

    report = run_candidate_selection(
        DataProvider(storage),
        cfg,
        goal=CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8),
        data_audit_status="PASS",
        robustness_status="PASS",
        specs=[spec],
    )
    result = report.results[0]

    assert result.spec.name == "price_volume_defensive"
    assert result.to_dict()["data_dependency"] == "ohlcv_only"
    assert {factor.name for factor in result.spec.factors}.isdisjoint({"value_ep", "quality_roe"})
    assert result.order_count > 0
    assert "total_return" in result.metrics
    assert storage.load_fundamentals(storage.load_all_bars_from_db_symbols(), "2020-12-31").empty


def test_low_turnover_price_volume_is_ohlcv_only_quarterly_candidate(tmp_path: Path) -> None:
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = next(item for item in default_candidate_specs(cfg) if item.name == "low_turnover_price_volume")

    assert spec.data_dependency == "ohlcv_only"
    assert spec.rebalance == "quarterly"
    assert spec.n_holdings >= 40
    assert spec.max_weight <= 0.035
    assert {factor.name for factor in spec.factors}.isdisjoint({"value_ep", "quality_roe"})


def test_low_turnover_low_concentration_price_volume_is_ohlcv_only_candidate(tmp_path: Path) -> None:
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = next(
        item
        for item in default_candidate_specs(cfg)
        if item.name == "low_turnover_low_concentration_price_volume"
    )

    assert spec.data_dependency == "ohlcv_only"
    assert spec.rebalance == "quarterly"
    assert spec.n_holdings >= 40
    assert spec.max_weight <= 0.0245
    assert {factor.name for factor in spec.factors}.isdisjoint({"value_ep", "quality_roe"})


def test_trend_filtered_price_volume_is_ohlcv_only_defensive_candidate(tmp_path: Path) -> None:
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = next(item for item in default_candidate_specs(cfg) if item.name == "trend_filtered_price_volume")

    assert spec.data_dependency == "ohlcv_only"
    assert spec.trend_filter is True
    assert spec.n_holdings >= 30
    assert spec.max_weight <= 0.035
    assert {factor.name for factor in spec.factors}.isdisjoint({"value_ep", "quality_roe"})


def test_trend_filtered_quarterly_price_volume_is_ohlcv_only_defensive_candidate(tmp_path: Path) -> None:
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = next(
        item
        for item in default_candidate_specs(cfg)
        if item.name == "trend_filtered_quarterly_price_volume"
    )

    assert spec.data_dependency == "ohlcv_only"
    assert spec.trend_filter is True
    assert spec.rebalance == "quarterly"
    assert spec.n_holdings >= 30
    assert spec.max_weight <= 0.035
    assert {factor.name for factor in spec.factors}.isdisjoint({"value_ep", "quality_roe"})


def test_trend_filtered_quarterly_low_concentration_price_volume_is_ohlcv_only_candidate(
    tmp_path: Path,
) -> None:
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = next(
        item
        for item in default_candidate_specs(cfg)
        if item.name == "trend_filtered_quarterly_low_concentration_price_volume"
    )

    assert spec.data_dependency == "ohlcv_only"
    assert spec.trend_filter is True
    assert spec.rebalance == "quarterly"
    assert spec.n_holdings >= 30
    assert spec.max_weight <= 0.0245
    assert {factor.name for factor in spec.factors}.isdisjoint({"value_ep", "quality_roe"})


def test_defensive_scaled_quarterly_price_volume_is_ohlcv_only_regime_scaled_candidate(
    tmp_path: Path,
) -> None:
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = next(
        item
        for item in default_candidate_specs(cfg)
        if item.name == "defensive_scaled_quarterly_price_volume"
    )

    assert spec.data_dependency == "ohlcv_only"
    assert spec.trend_filter is True
    assert spec.trend_scale == 0.15
    assert spec.trend_gate == "defensive_or_worse"
    assert spec.rebalance == "quarterly"
    assert spec.n_holdings >= 30
    assert spec.max_weight <= 0.03
    assert {factor.name for factor in spec.factors}.isdisjoint({"value_ep", "quality_roe"})


def test_stable_universe_slow_signal_price_volume_is_ohlcv_only_slow_signal_candidate(
    tmp_path: Path,
) -> None:
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = next(
        item
        for item in default_candidate_specs(cfg)
        if item.name == "stable_universe_slow_signal_price_volume"
    )
    factor_names = {factor.name for factor in spec.factors}

    assert spec.data_dependency == "ohlcv_only"
    assert spec.trend_filter is False
    assert spec.rebalance == "quarterly"
    assert spec.n_holdings >= 80
    assert spec.max_weight <= 0.02
    assert "long_momentum_120d_skip20d" in factor_names
    assert "momentum_20d" not in factor_names
    assert factor_names.isdisjoint({"value_ep", "quality_roe"})


def test_long_momentum_liquidity_monthly_price_volume_is_ohlcv_only_component_ablation_candidate(
    tmp_path: Path,
) -> None:
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = next(
        item
        for item in default_candidate_specs(cfg)
        if item.name == "long_momentum_liquidity_monthly_price_volume"
    )
    factor_names = {factor.name for factor in spec.factors}

    assert spec.data_dependency == "ohlcv_only"
    assert spec.trend_filter is False
    assert spec.rebalance == "monthly"
    assert spec.n_holdings >= 80
    assert spec.max_weight <= 0.02
    assert "long_momentum_120d_skip20d" in factor_names
    assert "liquidity_amount_20d" in factor_names
    assert "momentum_20d" not in factor_names
    assert factor_names.isdisjoint({"value_ep", "quality_roe"})


def test_liquidity_neutral_momentum_guard_price_volume_is_ohlcv_only_guarded_candidate(
    tmp_path: Path,
) -> None:
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = next(
        item
        for item in default_candidate_specs(cfg)
        if item.name == "liquidity_neutral_momentum_guard_price_volume"
    )
    factor_names = {factor.name for factor in spec.factors}

    assert spec.data_dependency == "ohlcv_only"
    assert spec.trend_filter is True
    assert spec.trend_scale == 0.15
    assert spec.trend_gate == "defensive_or_worse"
    assert spec.rebalance == "quarterly"
    assert spec.n_holdings >= 100
    assert spec.max_weight <= 0.015
    assert "liquidity_neutral_long_momentum_120d_skip20d" in factor_names
    assert "low_volatility_120d" in factor_names
    assert "liquidity_amount_20d" not in factor_names
    assert "momentum_20d" not in factor_names
    assert factor_names.isdisjoint({"value_ep", "quality_roe"})


def test_risk_off_cash_stop_is_ohlcv_only_full_cash_candidate(tmp_path: Path) -> None:
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = next(item for item in default_candidate_specs(cfg) if item.name == "risk_off_cash_stop_price_volume")

    assert spec.data_dependency == "ohlcv_only"
    assert spec.trend_filter is True
    assert spec.trend_scale == 0.0
    assert spec.trend_gate == "weak_trend"
    assert spec.n_holdings >= 80
    assert spec.max_weight <= 0.02
    assert {factor.name for factor in spec.factors}.isdisjoint({"value_ep", "quality_roe"})


def test_regime_pause_price_volume_is_ohlcv_only_regime_pause_candidate(tmp_path: Path) -> None:
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = next(item for item in default_candidate_specs(cfg) if item.name == "regime_pause_price_volume")

    assert spec.data_dependency == "ohlcv_only"
    assert spec.trend_filter is True
    assert spec.trend_gate == "defensive_or_worse"
    assert spec.n_holdings >= 30
    assert spec.max_weight <= 0.035
    assert {factor.name for factor in spec.factors}.isdisjoint({"value_ep", "quality_roe"})


def test_trend_filter_activates_on_broad_weak_market(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "weak.db")
    _seed_weak_market_data(storage)
    cfg = _ohlcv_cfg(tmp_path / "weak.db")
    spec = CandidateSpec(
        name="trend_filtered_test",
        description="trend-filtered test",
        factors=[MomentumFactor(), LowVolatilityFactor()],
        n_holdings=5,
        max_weight=0.05,
        rebalance="monthly",
        trend_filter=True,
        data_dependency="ohlcv_only",
    )

    report = run_candidate_selection(
        DataProvider(storage),
        cfg,
        goal=CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8),
        data_audit_status="PASS",
        robustness_status="PASS",
        specs=[spec],
    )

    assert report.results[0].trend_filter_active_days > 0


def test_risk_off_cash_stop_emits_zero_targets_on_broad_weak_market(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "weak.db")
    _seed_weak_market_data(storage)
    cfg = _ohlcv_cfg(tmp_path / "weak.db")
    data = DataProvider(storage)
    spec = next(item for item in default_candidate_specs(cfg) if item.name == "risk_off_cash_stop_price_volume")
    pipeline = FactorPipeline(factors=spec.factors)
    universe_filter = UniverseFilter(
        UniverseConfig(
            mode=cfg.universe.mode,
            index_code=cfg.universe.index_code,
            include_st=cfg.universe.include_st,
            min_history_days=cfg.universe.min_history_days,
        )
    )
    strategy = TrendFilteredTargetStrategy(
        universe_filter,
        pipeline,
        MultiFactorStrategyConfig(n_holdings=spec.n_holdings, max_weight=spec.max_weight),
        trend_scale=spec.trend_scale,
    )

    targets = strategy.on_rebalance("2020-12-31", data, Portfolio(initial_cash=100_000))

    assert targets
    assert strategy.active_days == 1
    assert sum(target.target_weight for target in targets) == 0.0


def test_regime_pause_zeroes_targets_on_defensive_or_risk_off_market(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "weak.db")
    _seed_weak_market_data(storage)
    cfg = _ohlcv_cfg(tmp_path / "weak.db")
    data = DataProvider(storage)
    spec = next(item for item in default_candidate_specs(cfg) if item.name == "regime_pause_price_volume")
    pipeline = FactorPipeline(factors=spec.factors)
    universe_filter = UniverseFilter(
        UniverseConfig(
            mode=cfg.universe.mode,
            index_code=cfg.universe.index_code,
            include_st=cfg.universe.include_st,
            min_history_days=cfg.universe.min_history_days,
        )
    )
    strategy = TrendFilteredTargetStrategy(
        universe_filter,
        pipeline,
        MultiFactorStrategyConfig(n_holdings=spec.n_holdings, max_weight=spec.max_weight),
        trend_scale=spec.trend_scale,
        trend_gate=spec.trend_gate,
        market_regime=_market_regime("defensive", status="PASS", end="2020-12-31"),
    )

    targets = strategy.on_rebalance("2020-12-31", data, Portfolio(initial_cash=100_000))

    assert targets
    assert strategy.active_days == 1
    assert sum(target.target_weight for target in targets) == 0.0


def test_fundamental_dependent_candidates_block_without_fundamentals(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "ohlcv.db")
    _seed_ohlcv_only_data(storage)
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")

    report = run_candidate_selection(
        DataProvider(storage),
        cfg,
        goal=CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8),
        data_audit_status="PASS",
        robustness_status="PASS",
    )
    by_name = {result.spec.name: result for result in report.results}

    assert by_name["price_volume_defensive"].data_dependency_review.status == "PASS"
    assert by_name["core_multifactor"].data_dependency_review.status == "BLOCK"
    assert by_name["core_multifactor"].score.decision == "BLOCK"
    assert by_name["value_low_vol"].data_dependency_review.field_coverage["pe_ttm"] == 0.0
    assert report.best_candidate == ""


def test_candidate_selection_blocks_risk_off_market_context(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "ohlcv.db")
    _seed_ohlcv_only_data(storage)
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = CandidateSpec(
        name="low_vol_test",
        description="low-volatility test",
        factors=[LowVolatilityFactor()],
        n_holdings=5,
        max_weight=0.05,
        rebalance="monthly",
        data_dependency="ohlcv_only",
    )

    report = run_candidate_selection(
        DataProvider(storage),
        cfg,
        goal=CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8),
        data_audit_status="PASS",
        robustness_status="PASS",
        market_regime=_market_regime("risk_off", status="WATCH", end="2020-12-31"),
        specs=[spec],
    )
    result = report.results[0]

    assert result.market_regime_review.status == "BLOCK"
    assert result.market_regime_review.fit == "adverse_market_pause"
    assert result.score.decision == "BLOCK"
    assert report.status == "BLOCK"
    assert report.selected_candidate == ""
    assert report.best_candidate == ""
    assert report.top_candidate == "low_vol_test"
    assert any("risk_off" in reason for reason in result.score.reasons)


def test_candidate_selection_watches_defensive_market_context(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "ohlcv.db")
    _seed_ohlcv_only_data(storage)
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    defensive_spec = CandidateSpec(
        name="low_vol_test",
        description="low-volatility test",
        factors=[LowVolatilityFactor()],
        n_holdings=5,
        max_weight=0.05,
        rebalance="monthly",
        data_dependency="ohlcv_only",
    )
    non_defensive_spec = CandidateSpec(
        name="momentum_test",
        description="momentum test",
        factors=[MomentumFactor()],
        n_holdings=5,
        max_weight=0.05,
        rebalance="monthly",
        data_dependency="ohlcv_only",
    )

    report = run_candidate_selection(
        DataProvider(storage),
        cfg,
        goal=CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8),
        data_audit_status="PASS",
        robustness_status="PASS",
        market_regime=_market_regime("defensive", status="WATCH", end="2020-12-31"),
        specs=[defensive_spec, non_defensive_spec],
    )
    by_name = {result.spec.name: result for result in report.results}

    assert by_name["low_vol_test"].market_regime_review.status == "WATCH"
    assert by_name["low_vol_test"].market_regime_review.fit == "defensive_fit"
    assert by_name["low_vol_test"].score.decision != "PASS"
    assert by_name["momentum_test"].market_regime_review.fit == "non_defensive_in_defensive_market"


def test_price_volume_defensive_is_defensive_aligned_in_defensive_market(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "ohlcv.db")
    _seed_ohlcv_only_data(storage)
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = next(item for item in default_candidate_specs(cfg) if item.name == "price_volume_defensive")

    report = run_candidate_selection(
        DataProvider(storage),
        cfg,
        goal=CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8),
        data_audit_status="PASS",
        robustness_status="PASS",
        market_regime=_market_regime("defensive", status="WATCH", end="2020-12-31"),
        specs=[spec],
    )
    result = report.results[0]

    assert result.market_regime_review.status == "WATCH"
    assert result.market_regime_review.fit == "defensive_fit"


def test_candidate_selection_blocks_mismatched_market_regime_window(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "ohlcv.db")
    _seed_ohlcv_only_data(storage)
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = CandidateSpec(
        name="low_vol_test",
        description="low-volatility test",
        factors=[LowVolatilityFactor()],
        n_holdings=5,
        max_weight=0.05,
        rebalance="monthly",
        data_dependency="ohlcv_only",
    )

    report = run_candidate_selection(
        DataProvider(storage),
        cfg,
        goal=CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8),
        data_audit_status="PASS",
        robustness_status="PASS",
        market_regime=_market_regime("neutral", status="PASS", end="2020-06-30", as_of="2020-06-30"),
        specs=[spec],
    )
    result = report.results[0]

    assert result.market_regime_review.status == "BLOCK"
    assert result.market_regime_review.alignment_status == "BLOCK"
    assert result.market_regime_review.fit == "misaligned_market_context"
    assert result.score.decision == "BLOCK"
    assert report.selected_candidate == ""
    assert any("does not match research end" in item for item in result.market_regime_review.alignment_findings)


def test_candidate_selection_watches_weak_market_regime_breadth(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "ohlcv.db")
    _seed_ohlcv_only_data(storage)
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = CandidateSpec(
        name="low_vol_test",
        description="low-volatility test",
        factors=[LowVolatilityFactor()],
        n_holdings=5,
        max_weight=0.05,
        rebalance="monthly",
        data_dependency="ohlcv_only",
    )

    report = run_candidate_selection(
        DataProvider(storage),
        cfg,
        goal=CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8),
        data_audit_status="PASS",
        robustness_status="PASS",
        market_regime=_market_regime(
            "neutral",
            status="PASS",
            end="2020-12-31",
            usable_symbol_count=3,
            trading_day_count=40,
        ),
        specs=[spec],
    )
    result = report.results[0]

    assert result.market_regime_review.status == "WATCH"
    assert result.market_regime_review.alignment_status == "WATCH"
    assert result.market_regime_review.fit == "weak_market_context"
    assert result.score.decision != "PASS"
    assert report.selected_candidate == ""


def test_candidate_selection_blocks_candidate_walk_forward_tail_loss(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "ohlcv.db")
    _seed_ohlcv_only_data(storage)
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = CandidateSpec(
        name="low_vol_test",
        description="low-volatility test",
        factors=[LowVolatilityFactor()],
        n_holdings=5,
        max_weight=0.05,
        rebalance="monthly",
        data_dependency="ohlcv_only",
    )

    report = run_candidate_selection(
        DataProvider(storage),
        cfg,
        goal=CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8),
        data_audit_status="PASS",
        robustness_status="PASS",
        market_regime=_market_regime("neutral", status="PASS", end="2020-12-31"),
        candidate_walk_forward=_candidate_walk_forward("low_vol_test", worst_total_return=-0.12),
        specs=[spec],
    )
    out = write_candidate_selection_report(report, tmp_path / "selection")
    payload = json.loads((out / "candidate_selection.json").read_text(encoding="utf-8"))
    csv = pd.read_csv(out / "candidate_selection.csv")
    result = report.results[0]

    assert result.candidate_walk_forward_review.status == "BLOCK"
    assert result.score.decision == "BLOCK"
    assert report.status == "BLOCK"
    assert report.selected_candidate == ""
    assert payload["results"][0]["candidate_walk_forward_status"] == "BLOCK"
    assert csv.loc[0, "candidate_walk_forward_worst_total_return"] == -0.12


def test_candidate_selection_watches_low_candidate_walk_forward_positive_ratio(
    tmp_path: Path,
) -> None:
    storage = BarStorage(tmp_path / "ohlcv.db")
    _seed_ohlcv_only_data(storage)
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = CandidateSpec(
        name="low_vol_test",
        description="low-volatility test",
        factors=[LowVolatilityFactor()],
        n_holdings=5,
        max_weight=0.05,
        rebalance="monthly",
        data_dependency="ohlcv_only",
    )

    report = run_candidate_selection(
        DataProvider(storage),
        cfg,
        goal=CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8),
        data_audit_status="PASS",
        robustness_status="PASS",
        market_regime=_market_regime("neutral", status="PASS", end="2020-12-31"),
        candidate_walk_forward=_candidate_walk_forward("low_vol_test", positive_return_ratio=0.0),
        specs=[spec],
    )
    result = report.results[0]

    assert result.candidate_walk_forward_review.status == "WATCH"
    assert result.candidate_walk_forward_review.positive_return_ratio == 0.0
    assert result.score.decision == "BLOCK"
    assert report.status == "BLOCK"
    assert report.selected_candidate == ""


@pytest.mark.parametrize(
    ("locked_decision", "expected_selected"),
    [("WATCH", "locked_candidate"), ("BLOCK", "")],
)
def test_candidate_selection_keeps_selection_safe_lock_over_full_sample_winner(
    monkeypatch,
    locked_decision: str,
    expected_selected: str,
) -> None:
    locked_spec = CandidateSpec(
        name="locked_candidate",
        description="selected before test",
        factors=[],
        n_holdings=1,
        max_weight=1.0,
        rebalance="monthly",
        data_dependency="ohlcv_only",
    )
    winner_spec = CandidateSpec(
        name="full_sample_winner",
        description="higher full-sample score",
        factors=[],
        n_holdings=1,
        max_weight=1.0,
        rebalance="monthly",
        data_dependency="ohlcv_only",
    )
    scores = {
        "locked_candidate": SimpleNamespace(score=70.0, decision=locked_decision),
        "full_sample_winner": SimpleNamespace(score=95.0, decision="PASS"),
    }

    def fake_run_candidate(_data, _cfg, _goal, spec, *_args):
        return SimpleNamespace(spec=spec, score=scores[spec.name])

    monkeypatch.setattr(candidates_module, "_run_candidate", fake_run_candidate)

    report = run_candidate_selection(
        SimpleNamespace(all_symbols=lambda: []),
        SimpleNamespace(),
        goal=CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8),
        data_audit_status="PASS",
        robustness_status="PASS",
        candidate_walk_forward=_candidate_walk_forward("locked_candidate"),
        specs=[locked_spec, winner_spec],
    )

    assert report.top_candidate == "full_sample_winner"
    assert report.selected_candidate == expected_selected
    assert report.best_candidate == expected_selected
    assert report.status == locked_decision


def test_candidate_walk_forward_review_blocks_legacy_evidence_without_selection_safety() -> None:
    spec = CandidateSpec(
        name="locked_candidate",
        description="selected before test",
        factors=[],
        n_holdings=1,
        max_weight=1.0,
        rebalance="monthly",
        data_dependency="ohlcv_only",
    )
    legacy_report = _candidate_walk_forward("locked_candidate")
    legacy_report.pop("selection_safe")

    review = candidates_module._review_candidate_walk_forward(legacy_report, spec)

    assert review.status == "BLOCK"
    assert any("selection-safe v2 contract" in finding for finding in review.findings)


def test_candidate_selection_blocks_candidate_regime_validation_failure(
    tmp_path: Path,
) -> None:
    storage = BarStorage(tmp_path / "ohlcv.db")
    _seed_ohlcv_only_data(storage)
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = CandidateSpec(
        name="low_vol_test",
        description="low-volatility test",
        factors=[LowVolatilityFactor()],
        n_holdings=5,
        max_weight=0.05,
        rebalance="monthly",
        data_dependency="ohlcv_only",
    )

    report = run_candidate_selection(
        DataProvider(storage),
        cfg,
        goal=CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8),
        data_audit_status="PASS",
        robustness_status="PASS",
        market_regime=_market_regime("neutral", status="PASS", end="2020-12-31"),
        candidate_walk_forward=_candidate_walk_forward("low_vol_test"),
        candidate_regime_validation=_candidate_regime_validation(
            "low_vol_test",
            status="BLOCK",
            block_bucket_count=1,
        ),
        specs=[spec],
    )
    out = write_candidate_selection_report(report, tmp_path / "selection")
    payload = json.loads((out / "candidate_selection.json").read_text(encoding="utf-8"))
    csv = pd.read_csv(out / "candidate_selection.csv")
    result = report.results[0]

    assert result.candidate_regime_validation_review.status == "BLOCK"
    assert result.score.decision == "BLOCK"
    assert report.status == "BLOCK"
    assert report.selected_candidate == ""
    assert payload["results"][0]["candidate_regime_validation_status"] == "BLOCK"
    assert csv.loc[0, "candidate_regime_block_bucket_count"] == 1


def test_candidate_selection_watches_missing_adverse_regime_validation(
    tmp_path: Path,
) -> None:
    storage = BarStorage(tmp_path / "ohlcv.db")
    _seed_ohlcv_only_data(storage)
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = CandidateSpec(
        name="low_vol_test",
        description="low-volatility test",
        factors=[LowVolatilityFactor()],
        n_holdings=5,
        max_weight=0.05,
        rebalance="monthly",
        data_dependency="ohlcv_only",
    )

    report = run_candidate_selection(
        DataProvider(storage),
        cfg,
        goal=CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8),
        data_audit_status="PASS",
        robustness_status="PASS",
        market_regime=_market_regime("neutral", status="PASS", end="2020-12-31"),
        candidate_walk_forward=_candidate_walk_forward("low_vol_test"),
        candidate_regime_validation=_candidate_regime_validation(
            "low_vol_test",
            status="PASS",
            adverse_regime_window_count=0,
        ),
        specs=[spec],
    )
    result = report.results[0]

    assert result.candidate_regime_validation_review.status == "WATCH"
    assert result.score.decision == "BLOCK"
    assert report.status == "BLOCK"
    assert report.selected_candidate == ""
    assert any(
        "No defensive or risk_off" in finding
        for finding in result.candidate_regime_validation_review.findings
    )


def test_candidate_selection_surfaces_capital_goal_fit_watch(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "ohlcv.db")
    _seed_ohlcv_only_data(storage)
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = CandidateSpec(
        name="low_vol_test",
        description="low-volatility test",
        factors=[LowVolatilityFactor()],
        n_holdings=5,
        max_weight=0.05,
        rebalance="monthly",
        data_dependency="ohlcv_only",
    )

    report = run_candidate_selection(
        DataProvider(storage),
        cfg,
        goal=CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8),
        data_audit_status="PASS",
        robustness_status="PASS",
        market_regime=_market_regime("neutral", status="PASS", end="2020-12-31"),
        candidate_walk_forward=_candidate_walk_forward("low_vol_test"),
        specs=[spec],
    )
    out = write_candidate_selection_report(report, tmp_path / "selection")
    payload = json.loads((out / "candidate_selection.json").read_text(encoding="utf-8"))
    csv = pd.read_csv(out / "candidate_selection.csv")
    result = report.results[0]

    assert result.capital_goal_fit_review.status in {"PASS", "WATCH", "BLOCK"}
    assert "capital_goal_fit_review" in payload["results"][0]
    assert "initial_turnover_pct" in payload["results"][0]
    assert "avg_maintenance_turnover_pct" in payload["results"][0]
    assert "max_maintenance_turnover_pct" in payload["results"][0]
    assert payload["results"][0]["capital_goal_fit_review"]["avg_maintenance_turnover_pct"] == (
        payload["results"][0]["avg_maintenance_turnover_pct"]
    )
    assert "capital_goal_fit_status" in csv.columns
    assert "capital_goal_return_margin" in csv.columns
    assert "capital_goal_avg_maintenance_turnover_pct" in csv.columns


def test_candidate_selection_blocks_negative_capital_goal_fit(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "ohlcv.db")
    _seed_ohlcv_only_data(storage, drift=-0.0004)
    cfg = _ohlcv_cfg(tmp_path / "ohlcv.db")
    spec = CandidateSpec(
        name="low_vol_test",
        description="low-volatility test",
        factors=[LowVolatilityFactor()],
        n_holdings=5,
        max_weight=0.05,
        rebalance="monthly",
        data_dependency="ohlcv_only",
    )

    report = run_candidate_selection(
        DataProvider(storage),
        cfg,
        goal=CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8),
        data_audit_status="PASS",
        robustness_status="PASS",
        market_regime=_market_regime("neutral", status="PASS", end="2020-12-31"),
        candidate_walk_forward=_candidate_walk_forward("low_vol_test"),
        specs=[spec],
    )
    result = report.results[0]

    assert result.capital_goal_fit_review.status == "BLOCK"
    assert result.score.decision == "BLOCK"
    assert report.selected_candidate == ""
    assert any("not positive" in item for item in result.capital_goal_fit_review.findings)


def _cfg(cache_path: Path) -> Config:
    return Config(
        {
            "research": {
                "start": "2020-04-01",
                "end": "2020-06-30",
                "initial_cash": 1_000_000.0,
                "rebalance": "monthly",
            },
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
            "data": {"cache_path": str(cache_path), "source": "demo"},
            "output": {"results_dir": str(cache_path.parent)},
        }
    )


def _ohlcv_cfg(cache_path: Path) -> Config:
    return Config(
        {
            "research": {
                "start": "2020-08-03",
                "end": "2020-12-31",
                "initial_cash": 1_000_000.0,
                "rebalance": "monthly",
            },
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
            "data": {"cache_path": str(cache_path), "source": "csv"},
            "output": {"results_dir": str(cache_path.parent)},
        }
    )


def _cfg_yaml(cache_path: Path) -> str:
    return f"""
research:
  start: "2020-04-01"
  end: "2020-06-30"
  in_sample_end: "2020-05-15"
  out_sample_start: "2020-05-18"
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


def _seed_ohlcv_only_data(storage: BarStorage, *, drift: float = 0.0002) -> None:
    symbols = [f"600{i:03d}" for i in range(1, 9)]
    dates = pd.bdate_range("2020-01-01", "2020-12-31")
    storage.save_calendar(dates)
    storage.save_stock_info(
        pd.DataFrame(
            {
                "symbol": symbols,
                "name": [f"alpha_{i}" for i, _symbol in enumerate(symbols, start=1)],
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
        returns = drift + idx * 0.00002
        close = 10.0 + idx + pd.Series(range(len(dates)), dtype=float) * returns * 10
        open_ = close * 0.999
        high = close * 1.01
        low = close * 0.99
        volume = 1_000_000 + idx * 10_000
        frames.append(
            pd.DataFrame(
                {
                    "symbol": symbol,
                    "date": [day.date().isoformat() for day in dates],
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "amount": close * volume,
                }
            )
        )
    storage.save_bars(pd.concat(frames, ignore_index=True))


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


def _market_regime(
    label: str,
    *,
    status: str,
    start: str = "2020-08-03",
    end: str = "2020-12-31",
    as_of: str | None = None,
    usable_symbol_count: int = 8,
    trading_day_count: int = 100,
) -> dict[str, object]:
    return {
        "status": status,
        "label": label,
        "start": start,
        "end": end,
        "as_of": as_of or end,
        "symbol_count": usable_symbol_count,
        "usable_symbol_count": usable_symbol_count,
        "trading_day_count": trading_day_count,
        "metrics": {},
        "findings": [],
    }


def _candidate_walk_forward(
    candidate: str,
    *,
    status: str = "PASS",
    positive_return_ratio: float = 1.0,
    worst_total_return: float = 0.01,
    worst_max_drawdown: float = 0.04,
) -> dict[str, object]:
    windows = [_candidate_wf_window(candidate, index) for index in range(1, 4)]
    return {
        "artifact_type": "candidate_walk_forward_report",
        "schema_version": 2,
        "selection_protocol": "quantify.walk-forward-selection.v2",
        "selection_safe": True,
        "test_used_for_selection": False,
        "configuration": {
            "mode": "expanding",
            "train_days": 2,
            "purge_days": 0,
            "selection_days": 1,
            "embargo_days": 0,
            "test_days": 1,
            "step_days": 1,
        },
        "status": status,
        "selected_candidate": candidate,
        "best_candidate": candidate,
        "candidate_count": 1,
        "window_count": 3,
        "selections": [
            {"candidate": candidate, "window": f"wf_{index:02d}", "rank": 1}
            for index in range(1, 4)
        ],
        "windows": windows,
        "summaries": [
            {
                "candidate": candidate,
                "status": status,
                "window_count": 3,
                "pass_count": 3 if status == "PASS" else 1,
                "watch_count": 0 if status == "PASS" else 2,
                "block_count": 1 if status == "BLOCK" else 0,
                "avg_total_return": 0.06,
                "avg_max_drawdown": 0.04,
                "avg_sharpe_ratio": 0.9,
                "positive_return_ratio": positive_return_ratio,
                "worst_total_return": worst_total_return,
                "worst_max_drawdown": worst_max_drawdown,
            }
        ],
    }


def _candidate_wf_window(candidate: str, index: int) -> dict[str, object]:
    train_end = index + 1
    selection_day = index + 2
    test_day = index + 3
    name = f"wf_{index:02d}"
    return {
        "candidate": candidate,
        "window": name,
        "selection_rank": 1,
        "start": f"d{test_day:02d}",
        "end": f"d{test_day:02d}",
        "phases": {
            "name": name,
            "mode": "expanding",
            "train": {
                "start": "d01",
                "end": f"d{train_end:02d}",
                "trading_day_count": train_end,
            },
            "purge": {"start": "", "end": "", "trading_day_count": 0},
            "selection": {
                "start": f"d{selection_day:02d}",
                "end": f"d{selection_day:02d}",
                "trading_day_count": 1,
            },
            "embargo": {"start": "", "end": "", "trading_day_count": 0},
            "test": {
                "start": f"d{test_day:02d}",
                "end": f"d{test_day:02d}",
                "trading_day_count": 1,
            },
        },
    }


def _candidate_regime_validation(
    candidate: str,
    *,
    status: str = "PASS",
    known_regime_count: int = 2,
    adverse_regime_window_count: int = 1,
    block_bucket_count: int = 0,
    warnings: list[str] | None = None,
) -> dict[str, object]:
    watch_bucket_count = 1 if status == "WATCH" else 0
    pass_bucket_count = 2 if status == "PASS" else 1
    return {
        "status": "WATCH" if warnings else status,
        "best_candidate": candidate,
        "candidate_count": 1,
        "window_count": 3,
        "regime_count": known_regime_count,
        "warnings": warnings or [],
        "summaries": [
            {
                "candidate": candidate,
                "status": status,
                "regime_count": known_regime_count,
                "known_regime_count": known_regime_count,
                "adverse_regime_window_count": adverse_regime_window_count,
                "pass_bucket_count": pass_bucket_count,
                "watch_bucket_count": watch_bucket_count,
                "block_bucket_count": block_bucket_count,
                "avg_total_return": 0.05,
                "avg_max_drawdown": 0.04,
                "avg_sharpe_ratio": 0.9,
                "notes": [],
            }
        ],
        "buckets": [],
        "windows": [],
    }
