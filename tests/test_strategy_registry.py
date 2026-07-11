from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from quantify.ops import update_candidate_registry


def test_strategy_registry_accumulates_candidate_history(tmp_path: Path) -> None:
    run1 = tmp_path / "run1"
    run2 = tmp_path / "run2"
    _write_run(run1, annual_return=0.12, decision="WATCH")
    _write_run(run2, annual_return=0.20, decision="PASS")
    registry_path = tmp_path / "registry" / "strategy_registry.json"

    first = update_candidate_registry(run1, registry_path=registry_path)
    second = update_candidate_registry(run2, registry_path=registry_path)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    core = payload["candidates"]["core_multifactor"]["summary"]

    assert first.run_count == 1
    assert second.run_count == 2
    assert core["observations"] == 2
    assert core["pass_count"] == 1
    assert core["watch_count"] == 1
    assert core["real_observation_count"] == 2
    assert core["demo_observation_count"] == 0
    assert core["promotion_eligible"] is False
    assert "3 real-data observations" in core["promotion_reason"]
    assert (registry_path.parent / "strategy_registry.md").exists()
    assert (run2 / "strategy_registry_snapshot.json").exists()


def test_strategy_registry_does_not_promote_demo_only_history(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry" / "strategy_registry.json"
    for idx in range(3):
        run = tmp_path / f"demo_run_{idx}"
        _write_run(run, annual_return=0.50, decision="PASS", demo_data_used=True)
        update_candidate_registry(run, registry_path=registry_path)

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    summary = payload["candidates"]["core_multifactor"]["summary"]

    assert summary["demo_observation_count"] == 3
    assert summary["real_observation_count"] == 0
    assert summary["promotion_eligible"] is False
    assert "real-data observations" in summary["promotion_reason"]


def test_strategy_registry_marks_real_strategy_eligible_after_repeated_passes(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry" / "strategy_registry.json"
    for idx, decision in enumerate(["PASS", "WATCH", "PASS"]):
        run = tmp_path / f"real_run_{idx}"
        _write_run(
            run,
            annual_return=0.22,
            decision=decision,
            demo_data_used=False,
            candidate_walk_forward_status="PASS",
            candidate_regime_status="PASS",
        )
        update_candidate_registry(run, registry_path=registry_path)

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    summary = payload["candidates"]["core_multifactor"]["summary"]

    assert summary["real_observation_count"] == 3
    assert summary["real_pass_count"] == 2
    assert summary["real_candidate_walk_forward_observation_count"] == 3
    assert summary["real_candidate_walk_forward_pass_count"] == 3
    assert summary["real_avg_candidate_walk_forward_positive_return_ratio"] == 1.0
    assert summary["real_worst_candidate_walk_forward_return"] == 0.01
    assert summary["real_worst_candidate_walk_forward_drawdown"] == 0.06
    assert summary["real_candidate_regime_observation_count"] == 3
    assert summary["real_candidate_regime_pass_count"] == 3
    assert summary["promotion_eligible"] is True
    assert "not a live trading instruction" in summary["promotion_reason"]


def test_strategy_registry_requires_candidate_walk_forward_for_promotion(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry" / "strategy_registry.json"
    for idx, decision in enumerate(["PASS", "WATCH", "PASS"]):
        run = tmp_path / f"real_run_{idx}"
        _write_run(run, annual_return=0.22, decision=decision, demo_data_used=False)
        update_candidate_registry(run, registry_path=registry_path)

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    summary = payload["candidates"]["core_multifactor"]["summary"]

    assert summary["real_observation_count"] == 3
    assert summary["real_candidate_walk_forward_observation_count"] == 0
    assert summary["promotion_eligible"] is False
    assert "candidate walk-forward" in summary["promotion_reason"]


def test_strategy_registry_requires_candidate_regime_validation_for_promotion(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry" / "strategy_registry.json"
    for idx, decision in enumerate(["PASS", "WATCH", "PASS"]):
        run = tmp_path / f"real_run_{idx}"
        _write_run(
            run,
            annual_return=0.22,
            decision=decision,
            demo_data_used=False,
            candidate_walk_forward_status="PASS",
        )
        update_candidate_registry(run, registry_path=registry_path)

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    summary = payload["candidates"]["core_multifactor"]["summary"]

    assert summary["real_candidate_walk_forward_observation_count"] == 3
    assert summary["real_candidate_regime_observation_count"] == 0
    assert summary["promotion_eligible"] is False
    assert "candidate regime validation" in summary["promotion_reason"]


def test_strategy_registry_blocks_promotion_on_candidate_walk_forward_tail_loss(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry" / "strategy_registry.json"
    for idx, decision in enumerate(["PASS", "WATCH", "PASS"]):
        run = tmp_path / f"real_run_{idx}"
        _write_run(
            run,
            annual_return=0.22,
            decision=decision,
            demo_data_used=False,
            candidate_walk_forward_status="PASS",
            candidate_regime_status="PASS",
            candidate_walk_forward_worst_return=-0.12 if idx == 2 else 0.01,
        )
        update_candidate_registry(run, registry_path=registry_path)

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    summary = payload["candidates"]["core_multifactor"]["summary"]

    assert summary["real_worst_candidate_walk_forward_return"] == -0.12
    assert summary["promotion_eligible"] is False
    assert "lost more than 10%" in summary["promotion_reason"]


def test_strategy_registry_cli_updates_json(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_run(run_dir, annual_return=0.12, decision="WATCH")
    registry_path = tmp_path / "strategy_registry.json"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/update_strategy_registry.py",
            "--report-dir",
            str(run_dir),
            "--registry",
            str(registry_path),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert registry_path.exists()
    assert "core_multifactor" in registry_path.read_text(encoding="utf-8")


def _write_run(
    root: Path,
    *,
    annual_return: float,
    decision: str,
    demo_data_used: bool = False,
    candidate_walk_forward_status: str | None = None,
    candidate_regime_status: str | None = None,
    candidate_walk_forward_positive_ratio: float = 1.0,
    candidate_walk_forward_worst_return: float = 0.01,
    candidate_walk_forward_worst_drawdown: float = 0.06,
) -> None:
    root.mkdir(parents=True)
    (root / "candidate_selection.json").write_text(
        json.dumps(
            {
                "status": decision,
                "best_candidate": "core_multifactor",
                "market_regime": {"label": "neutral", "status": "PASS"},
                "results": [
                    {
                        "name": "core_multifactor",
                        "description": "Core test candidate",
                        "factors": ["momentum", "low_volatility"],
                        "score": {"decision": decision, "score": 80.0},
                        "metrics": {
                            "annualized_return": annual_return,
                            "max_drawdown": 0.08,
                            "sharpe_ratio": 1.1,
                        },
                        "reject_rate": 0.0,
                        "avg_turnover_pct": 0.2,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "weekly_review.json").write_text(json.dumps({"decision": "research_only"}), encoding="utf-8")
    (root / "data_audit.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    (root / "robustness_report.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    (root / "llm_review.json").write_text(json.dumps({"decision": "WATCH"}), encoding="utf-8")
    if candidate_walk_forward_status is not None:
        (root / "candidate_walk_forward_report.json").write_text(
            json.dumps(
                {
                    "status": candidate_walk_forward_status,
                    "best_candidate": "core_multifactor",
                    "summaries": [
                        {
                            "candidate": "core_multifactor",
                            "status": candidate_walk_forward_status,
                            "window_count": 3,
                            "pass_count": 3 if candidate_walk_forward_status == "PASS" else 1,
                            "watch_count": 0 if candidate_walk_forward_status == "PASS" else 2,
                            "block_count": 0,
                            "avg_total_return": 0.04,
                            "avg_max_drawdown": 0.05,
                            "avg_sharpe_ratio": 1.0,
                            "avg_reject_rate": 0.0,
                            "positive_return_ratio": candidate_walk_forward_positive_ratio,
                            "worst_total_return": candidate_walk_forward_worst_return,
                            "worst_max_drawdown": candidate_walk_forward_worst_drawdown,
                            "notes": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
    if candidate_regime_status is not None:
        (root / "candidate_regime_validation_report.json").write_text(
            json.dumps(
                {
                    "status": candidate_regime_status,
                    "best_candidate": "core_multifactor",
                    "summaries": [
                        {
                            "candidate": "core_multifactor",
                            "status": candidate_regime_status,
                            "regime_count": 2,
                            "known_regime_count": 2,
                            "adverse_regime_window_count": 1,
                            "pass_bucket_count": 2 if candidate_regime_status == "PASS" else 0,
                            "watch_bucket_count": 0 if candidate_regime_status == "PASS" else 2,
                            "block_bucket_count": 0,
                            "avg_total_return": 0.04,
                            "avg_max_drawdown": 0.05,
                            "avg_sharpe_ratio": 1.0,
                            "notes": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
    (root / "summary.json").write_text(
        json.dumps({"assumptions": {"demo_data_used": demo_data_used}}),
        encoding="utf-8",
    )
