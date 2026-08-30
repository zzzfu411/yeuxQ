from __future__ import annotations

from types import SimpleNamespace

import pytest

import quantify.research.candidate_walk_forward as candidate_wf
from quantify.research.candidate_walk_forward import run_candidate_walk_forward
from quantify.research.candidates import CandidateSpec
from quantify.research.walk_forward_protocol import (
    CANDIDATE_WALK_FORWARD_ARTIFACT,
    build_walk_forward_folds,
    validate_selection_safe_payload,
)


def test_protocol_orders_all_phases_and_prevents_overlapping_tests() -> None:
    days = [f"2026-01-{day:02d}" for day in range(1, 31)]

    folds = build_walk_forward_folds(
        days,
        train_days=8,
        purge_days=2,
        selection_days=4,
        embargo_days=2,
        test_days=4,
        step_days=4,
        mode="rolling",
    )

    assert len(folds) >= 2
    first, second = folds[:2]
    assert first.train.end < first.purge.start
    assert first.purge.end < first.selection.start
    assert first.selection.end < first.embargo.start
    assert first.embargo.end < first.test.start
    assert first.test.end < second.test.start
    assert first.train.start < second.train.start


def test_expanding_train_keeps_origin_while_rolling_train_moves() -> None:
    days = [f"d{day:03d}" for day in range(40)]
    common = {
        "train_days": 8,
        "purge_days": 1,
        "selection_days": 4,
        "embargo_days": 1,
        "test_days": 4,
        "step_days": 4,
    }

    expanding = build_walk_forward_folds(days, mode="expanding", **common)
    rolling = build_walk_forward_folds(days, mode="rolling", **common)

    assert expanding[0].train.start == expanding[1].train.start
    assert expanding[1].train.trading_day_count > expanding[0].train.trading_day_count
    assert rolling[0].train.start != rolling[1].train.start
    assert rolling[0].train.trading_day_count == rolling[1].train.trading_day_count


def test_protocol_rejects_overlapping_test_steps() -> None:
    with pytest.raises(ValueError, match="step_days"):
        build_walk_forward_folds(
            [f"d{day:03d}" for day in range(30)],
            train_days=8,
            purge_days=1,
            selection_days=4,
            embargo_days=1,
            test_days=5,
            step_days=4,
            mode="expanding",
        )


def test_protocol_rejects_unsorted_trading_days() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        build_walk_forward_folds(
            ["d01", "d03", "d02", "d04", "d05", "d06"],
            train_days=2,
            purge_days=0,
            selection_days=1,
            embargo_days=0,
            test_days=1,
            step_days=1,
            mode="expanding",
        )


def test_bare_selection_safe_boolean_does_not_satisfy_v2_contract() -> None:
    validation = validate_selection_safe_payload(
        {"status": "PASS", "selection_safe": True},
        artifact_type=CANDIDATE_WALK_FORWARD_ARTIFACT,
    )

    assert validation.safe is False
    assert any("schema_version" in reason for reason in validation.reasons)
    assert any("test_used_for_selection" in reason for reason in validation.reasons)


def test_candidate_is_locked_before_test_and_test_only_downgrades(monkeypatch) -> None:
    days = [f"d{day:03d}" for day in range(16)]
    data = SimpleNamespace(trading_days=lambda _start, _end: days)
    cfg = SimpleNamespace(research=SimpleNamespace(start=days[0], end=days[-1]))
    specs = [
        CandidateSpec(
            name="selection_winner",
            description="wins before test",
            factors=[],
            n_holdings=1,
            max_weight=1.0,
            rebalance="monthly",
        ),
        CandidateSpec(
            name="test_winner",
            description="would win only if test were inspected",
            factors=[],
            n_holdings=1,
            max_weight=1.0,
            rebalance="monthly",
        ),
    ]
    test_calls: list[str] = []

    def fake_phase(_data, _cfg, spec, phase, *, market_regime):
        del market_regime
        if phase.start in {"d009", "d012"}:
            test_calls.append(spec.name)
            test_return = -0.20 if spec.name == "selection_winner" else 0.50
            status = "BLOCK" if test_return < 0 else "PASS"
            return candidate_wf._PhaseResult(
                status=status,
                metrics=_metrics(test_return),
                reject_rate=0.0,
                trend_filter_active_days=0,
                notes=[],
            )
        selection_return = 0.20 if spec.name == "selection_winner" else 0.10
        return candidate_wf._PhaseResult(
            status="PASS",
            metrics=_metrics(selection_return),
            reject_rate=0.0,
            trend_filter_active_days=0,
            notes=[],
        )

    monkeypatch.setattr(candidate_wf, "_run_candidate_phase", fake_phase)

    report = run_candidate_walk_forward(
        data,
        cfg,
        train_days=4,
        purge_days=1,
        selection_days=3,
        embargo_days=1,
        test_days=3,
        step_days=3,
        specs=specs,
    )

    assert test_calls == ["selection_winner", "selection_winner"]
    assert report.best_candidate == "selection_winner"
    assert report.test_used_for_selection is False
    assert report.selection_safe is True
    assert report.status == "BLOCK"
    assert all(window.candidate == "selection_winner" for window in report.windows)
    assert all(window.test_status == "BLOCK" for window in report.windows)
    validation = validate_selection_safe_payload(
        report.to_dict(),
        artifact_type=CANDIDATE_WALK_FORWARD_ARTIFACT,
    )
    assert validation.safe is True


def _metrics(total_return: float) -> dict[str, float]:
    return {
        "total_return": total_return,
        "max_drawdown": 0.30 if total_return < 0 else 0.01,
        "sharpe_ratio": 2.0,
    }
