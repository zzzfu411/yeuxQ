from __future__ import annotations

from types import SimpleNamespace
from copy import deepcopy

import pytest

import quantify.research.robustness as robustness
from quantify.research.robustness import (
    RobustnessScenario,
    RobustnessScenarioResult,
    default_scenarios,
    run_robustness,
)
from quantify.research.walk_forward_protocol import (
    ROBUSTNESS_REQUIRED_SCENARIOS,
    validate_robustness_selection_safe_payload,
)


def test_every_frozen_scenario_runs_on_every_test_fold(monkeypatch) -> None:
    days = [f"d{day:03d}" for day in range(16)]
    data = SimpleNamespace(trading_days=lambda _start, _end: days)
    cfg = SimpleNamespace(research=SimpleNamespace(start=days[0], end=days[-1]))
    scenarios = [_scenario(name) for name in ROBUSTNESS_REQUIRED_SCENARIOS]
    frozen_names = list(ROBUSTNESS_REQUIRED_SCENARIOS)
    calls: list[tuple[str, str, str]] = []

    def fake_run(_data, _cfg, scenario, *, start, end):
        calls.append((scenario.name, start, end))
        if len(calls) == 1:
            scenarios.append(_scenario("added_after_results_started"))
        status = "BLOCK" if scenario.name == "baseline" and start == "d009" else "PASS"
        total_return = -0.20 if status == "BLOCK" else 0.10
        return _result(scenario.name, status, total_return)

    monkeypatch.setattr(robustness, "_run_scenario", fake_run)

    report = run_robustness(
        data,
        cfg,
        scenarios,
        train_days=4,
        purge_days=1,
        selection_days=3,
        embargo_days=1,
        test_days=3,
        step_days=3,
    )

    assert calls == [
        *((name, "d009", "d011") for name in frozen_names),
        *((name, "d012", "d014") for name in frozen_names),
    ]
    assert [scenario.name for scenario in report.scenario_matrix] == frozen_names
    assert [scenario.name for scenario in report.scenarios] == frozen_names
    assert all(
        [scenario.name for scenario in fold.scenarios] == frozen_names
        for fold in report.folds
    )
    assert report.scenarios[0].fold_count == 2
    assert report.scenarios[0].block_count == 1
    assert report.scenarios[0].metrics["total_return"] == pytest.approx(-0.05)
    assert report.status == "BLOCK"

    payload = report.to_dict()
    assert payload["artifact_type"] == "robustness_report"
    assert payload["schema_version"] == 2
    assert payload["selection_protocol"] == "quantify.robustness-selection.v2"
    assert payload["selection_safe"] is True
    assert payload["test_used_for_selection"] is False
    assert payload["scenario_matrix_frozen"] is True
    assert payload["evidence_role"] == "promotion_candidate"
    assert payload["configuration"]["test_days"] == 3
    assert all(fold["evaluation_phase"] == "test" for fold in payload["folds"])
    assert validate_robustness_selection_safe_payload(payload).safe is True

    tampered = deepcopy(payload)
    tampered["folds"][0]["scenarios"].pop()
    validation = validate_robustness_selection_safe_payload(tampered)
    assert validation.safe is False
    assert any("frozen matrix" in reason for reason in validation.reasons)


def test_fewer_than_three_complete_folds_cannot_pass(monkeypatch) -> None:
    days = [f"d{day:03d}" for day in range(16)]
    data = SimpleNamespace(trading_days=lambda _start, _end: days)
    cfg = SimpleNamespace(research=SimpleNamespace(start=days[0], end=days[-1]))
    scenarios = [_scenario(name) for name in ROBUSTNESS_REQUIRED_SCENARIOS]
    monkeypatch.setattr(
        robustness,
        "_run_scenario",
        lambda _data, _cfg, scenario, *, start, end: _result(
            scenario.name,
            "PASS",
            0.10,
        ),
    )

    report = run_robustness(
        data,
        cfg,
        scenarios,
        train_days=4,
        purge_days=1,
        selection_days=3,
        embargo_days=1,
        test_days=3,
        step_days=3,
    )

    assert len(report.folds) == 2
    assert report.selection_safe is True
    assert report.status == "WATCH"
    assert any("at least 3" in warning for warning in report.warnings)


def test_non_baseline_subset_is_not_mislabeled_as_baseline(monkeypatch) -> None:
    days = [f"d{day:03d}" for day in range(16)]
    data = SimpleNamespace(trading_days=lambda _start, _end: days)
    cfg = SimpleNamespace(research=SimpleNamespace(start=days[0], end=days[-1]))
    monkeypatch.setattr(
        robustness,
        "_run_scenario",
        lambda _data, _cfg, scenario, *, start, end: _result(
            scenario.name,
            "PASS",
            0.10,
        ),
    )

    report = run_robustness(
        data,
        cfg,
        [_scenario("high_cost")],
        train_days=4,
        purge_days=1,
        selection_days=3,
        embargo_days=1,
        test_days=3,
        step_days=3,
    )

    assert report.baseline_scenario is None
    assert report.baseline == {}
    assert report.selection_safe is False
    assert validate_robustness_selection_safe_payload(report.to_dict()).safe is False


def test_high_cost_scenario_has_nonzero_floors() -> None:
    cfg = SimpleNamespace(
        strategy=SimpleNamespace(n_holdings=10, max_weight=0.10),
        research=SimpleNamespace(rebalance="monthly"),
        broker=SimpleNamespace(
            commission_rate=0.0,
            min_commission=0.0,
            stamp_tax=0.0,
            slippage_bps=0.0,
        ),
    )

    high_cost = next(item for item in default_scenarios(cfg) if item.name == "high_cost")

    assert high_cost.commission_rate > 0.0
    assert high_cost.min_commission > 0.0
    assert high_cost.stamp_tax > 0.0
    assert high_cost.slippage_bps > 0.0


def test_no_complete_fold_blocks_and_is_not_selection_safe(monkeypatch) -> None:
    days = [f"d{day:03d}" for day in range(8)]
    data = SimpleNamespace(trading_days=lambda _start, _end: days)
    cfg = SimpleNamespace(research=SimpleNamespace(start=days[0], end=days[-1]))

    def unexpected_run(*_args, **_kwargs):
        raise AssertionError("No scenario should run without a complete fold.")

    monkeypatch.setattr(robustness, "_run_scenario", unexpected_run)

    report = run_robustness(
        data,
        cfg,
        [_scenario("baseline")],
        train_days=4,
        purge_days=1,
        selection_days=2,
        embargo_days=1,
        test_days=2,
        step_days=2,
    )

    assert report.status == "BLOCK"
    assert report.selection_safe is False
    assert report.folds == []
    assert report.scenarios[0].fold_count == 0
    assert report.to_dict()["selection_safe"] is False
    assert validate_robustness_selection_safe_payload(report.to_dict()).safe is False


def _scenario(name: str) -> RobustnessScenario:
    return RobustnessScenario(
        name=name,
        n_holdings=5,
        max_weight=0.10,
        rebalance="monthly",
        commission_rate=0.0,
        min_commission=0.0,
        stamp_tax=0.0,
        slippage_bps=0.0,
    )


def _result(
    name: str,
    status: robustness.RobustnessStatus,
    total_return: float,
) -> RobustnessScenarioResult:
    return RobustnessScenarioResult(
        name=name,
        status=status,
        metrics={
            "total_return": total_return,
            "max_drawdown": 0.30 if status == "BLOCK" else 0.01,
            "sharpe_ratio": 1.0,
            "n_bars": 3,
        },
        order_count=10,
        reject_rate=0.0,
        avg_turnover_pct=0.1,
        notes=[],
        fold_count=1,
        pass_count=int(status == "PASS"),
        watch_count=int(status == "WATCH"),
        block_count=int(status == "BLOCK"),
    )
