from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from quantify.goal import CapitalGoal
from quantify.ops import review_strategy_promotions, write_strategy_promotion_review


def test_strategy_promotion_blocks_demo_only_registry(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    _write_registry(
        registry,
        {
            "core_multifactor": _summary(real_obs=0, demo_obs=3, real_pass=0, real_return=0.0),
        },
    )

    review = review_strategy_promotions(registry, goal=_goal())

    assert review.decision == "BLOCK"
    candidate = review.candidates[0]
    assert candidate.decision == "BLOCK"
    assert any(finding.code == "INSUFFICIENT_REAL_OBSERVATIONS" for finding in candidate.findings)


def test_strategy_promotion_watches_when_return_below_goal(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    _write_registry(
        registry,
        {
            "core_multifactor": _summary(
                real_obs=3,
                demo_obs=0,
                real_pass=2,
                real_return=0.10,
                wf_obs=3,
                wf_pass=2,
                regime_obs=3,
                regime_pass=1,
                adverse_windows=1,
            ),
        },
    )

    review = review_strategy_promotions(registry, goal=_goal())

    assert review.decision == "WATCH"
    assert review.candidates[0].decision == "WATCH"
    assert any(finding.code == "RETURN_BELOW_GOAL_PATH" for finding in review.candidates[0].findings)


def test_strategy_promotion_passes_only_for_real_goal_aligned_candidate(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    _write_registry(
        registry,
        {
            "core_multifactor": _summary(
                real_obs=3,
                demo_obs=0,
                real_pass=2,
                real_return=0.36,
                wf_obs=3,
                wf_pass=2,
                regime_obs=3,
                regime_pass=1,
                adverse_windows=1,
            ),
        },
    )
    out = tmp_path / "out"

    result_dir = write_strategy_promotion_review(registry, out, goal=_goal())
    review = json.loads((result_dir / "strategy_promotion_review.json").read_text(encoding="utf-8"))

    assert review["decision"] == "PASS"
    assert review["candidates"][0]["decision"] == "PASS"
    assert (out / "strategy_promotion_review.md").exists()


def test_strategy_promotion_blocks_candidate_walk_forward_tail_loss(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    _write_registry(
        registry,
        {
            "core_multifactor": _summary(
                real_obs=3,
                demo_obs=0,
                real_pass=2,
                real_return=0.36,
                wf_obs=3,
                wf_pass=3,
                wf_worst_return=-0.12,
                regime_obs=3,
                regime_pass=1,
                adverse_windows=1,
            ),
        },
    )

    review = review_strategy_promotions(registry, goal=_goal())

    assert review.decision == "BLOCK"
    assert review.candidates[0].decision == "BLOCK"
    assert any(
        finding.code == "CANDIDATE_WALK_FORWARD_TAIL_LOSS"
        for finding in review.candidates[0].findings
    )


def test_strategy_promotion_cli_writes_outputs(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    _write_registry(
        registry,
        {
            "core_multifactor": _summary(
                real_obs=3,
                demo_obs=0,
                real_pass=2,
                real_return=0.36,
                wf_obs=3,
                wf_pass=2,
                regime_obs=3,
                regime_pass=1,
                adverse_windows=1,
            ),
        },
    )
    out = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/review_strategy_promotions.py",
            "--registry",
            str(registry),
            "--output-dir",
            str(out),
            "--years",
            "8",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert (out / "strategy_promotion_review.json").exists()


def test_strategy_promotion_blocks_missing_candidate_walk_forward_evidence(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    _write_registry(
        registry,
        {
            "core_multifactor": _summary(real_obs=3, demo_obs=0, real_pass=2, real_return=0.36),
        },
    )

    review = review_strategy_promotions(registry, goal=_goal())

    assert review.decision == "BLOCK"
    assert any(
        finding.code == "INSUFFICIENT_CANDIDATE_WALK_FORWARD_OBSERVATIONS"
        for finding in review.candidates[0].findings
    )


def test_strategy_promotion_blocks_missing_candidate_regime_evidence(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    _write_registry(
        registry,
        {
            "core_multifactor": _summary(
                real_obs=3,
                demo_obs=0,
                real_pass=2,
                real_return=0.36,
                wf_obs=3,
                wf_pass=2,
            ),
        },
    )

    review = review_strategy_promotions(registry, goal=_goal())

    assert review.decision == "BLOCK"
    assert any(
        finding.code == "INSUFFICIENT_CANDIDATE_REGIME_OBSERVATIONS"
        for finding in review.candidates[0].findings
    )


def test_strategy_promotion_blocks_direct_legacy_registry_summary(tmp_path: Path) -> None:
    registry = tmp_path / "legacy_registry.json"
    summary = _summary(
        real_obs=3,
        demo_obs=0,
        real_pass=3,
        real_return=0.50,
        wf_obs=3,
        wf_pass=3,
        regime_obs=3,
        regime_pass=3,
        adverse_windows=2,
    )
    summary.pop("selection_contract_version")
    summary.pop("selection_safe_real_observation_count")
    registry.write_text(
        json.dumps({"runs": [], "candidates": {"core_multifactor": {"summary": summary}}}),
        encoding="utf-8",
    )

    review = review_strategy_promotions(registry, goal=_goal())

    assert review.decision == "BLOCK"
    codes = {finding.code for finding in review.candidates[0].findings}
    assert "UNSAFE_REGISTRY_SCHEMA" in codes
    assert "MISSING_SELECTION_CONTRACT" in codes


def _goal() -> CapitalGoal:
    return CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8)


def _summary(
    *,
    real_obs: int,
    demo_obs: int,
    real_pass: int,
    real_return: float,
    wf_obs: int = 0,
    wf_pass: int = 0,
    wf_positive: float | None = None,
    wf_worst_return: float = 0.01,
    wf_worst_drawdown: float = 0.06,
    regime_obs: int = 0,
    regime_pass: int = 0,
    adverse_windows: float = 0.0,
) -> dict:
    return {
        "name": "core_multifactor",
        "selection_contract_version": 3,
        "statistical_evidence_contract_version": 3,
        "selection_safe_real_observation_count": real_obs,
        "statistical_safe_real_observation_count": real_obs,
        "real_observation_count": real_obs,
        "demo_observation_count": demo_obs,
        "real_pass_count": real_pass,
        "real_block_count": 0,
        "real_candidate_walk_forward_observation_count": wf_obs,
        "real_candidate_walk_forward_pass_count": wf_pass,
        "real_candidate_walk_forward_block_count": 0,
        "real_avg_candidate_walk_forward_pass_ratio": wf_pass / wf_obs if wf_obs else 0.0,
        "real_avg_candidate_walk_forward_positive_return_ratio": (
            wf_positive if wf_positive is not None else (1.0 if wf_obs else 0.0)
        ),
        "real_worst_candidate_walk_forward_return": wf_worst_return if wf_obs else 0.0,
        "real_worst_candidate_walk_forward_drawdown": wf_worst_drawdown if wf_obs else 0.0,
        "real_candidate_regime_observation_count": regime_obs,
        "real_candidate_regime_pass_count": regime_pass,
        "real_candidate_regime_block_count": 0,
        "real_avg_candidate_regime_adverse_window_count": adverse_windows,
        "real_avg_annualized_return": real_return,
        "real_avg_max_drawdown": 0.08,
        "real_avg_sharpe_ratio": 1.1,
    }


def _write_registry(path: Path, summaries: dict[str, dict]) -> None:
    payload = {
        "schema_version": 3,
        "runs": [],
        "candidates": {
            name: {"summary": summary}
            for name, summary in summaries.items()
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
