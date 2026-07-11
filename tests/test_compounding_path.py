from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from quantify.goal import CapitalGoal, build_compounding_path_review, write_compounding_path_review


def test_compounding_path_blocks_missing_evidence(tmp_path: Path) -> None:
    review = build_compounding_path_review(tmp_path, goal=_goal())
    out = write_compounding_path_review(review, tmp_path / "goal")

    payload = json.loads((out / "compounding_path_review.json").read_text(encoding="utf-8"))
    codes = {finding["code"] for finding in payload["findings"]}
    assert review.decision == "BLOCK"
    assert "NO_SELECTED_CANDIDATE" in codes
    assert "CANDIDATE_SELECTION_NOT_PASS" in codes
    assert "PAPER_STABILITY_MISSING" in codes
    assert (out / "compounding_path_review.md").exists()


def test_compounding_path_passes_complete_goal_aligned_evidence(tmp_path: Path) -> None:
    _write_complete_evidence(tmp_path, annual_return=0.35, max_drawdown=0.08, sharpe=1.2)

    review = build_compounding_path_review(tmp_path, goal=_goal())

    assert review.decision == "PASS"
    assert review.selected_candidate == "price_volume_defensive"
    assert review.projected_capital_at_horizon >= _goal().target_capital
    assert review.capital_shortfall == 0.0


def test_compounding_path_watches_return_below_required_path(tmp_path: Path) -> None:
    _write_complete_evidence(tmp_path, annual_return=0.10, max_drawdown=0.08, sharpe=1.2)

    review = build_compounding_path_review(tmp_path, goal=_goal())

    assert review.decision == "WATCH"
    assert any(finding.code == "RETURN_BELOW_REQUIRED_PATH" for finding in review.findings)
    assert review.capital_shortfall > 0


def test_compounding_path_surfaces_capital_goal_blocker(tmp_path: Path) -> None:
    _write_complete_evidence(tmp_path, annual_return=0.35, max_drawdown=0.08, sharpe=1.2)
    _write_json(
        tmp_path / "goal" / "capital_goal_status.json",
        {
            "decision": "BLOCK",
            "blockers": ["RUN_MANIFEST: missing source QA evidence manifest."],
        },
    )

    review = build_compounding_path_review(tmp_path, goal=_goal())

    assert review.decision == "BLOCK"
    finding = next(finding for finding in review.findings if finding.code == "CAPITAL_GOAL_STATUS_NOT_PASS")
    assert "RUN_MANIFEST" in finding.message


def test_compounding_path_cli_returns_nonzero_on_block(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_compounding_path_review.py",
            "--report-dir",
            str(tmp_path),
            "--years",
            "8",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((tmp_path / "goal" / "compounding_path_review.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"


def _goal() -> CapitalGoal:
    return CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8)


def _write_complete_evidence(
    root: Path,
    *,
    annual_return: float,
    max_drawdown: float,
    sharpe: float,
) -> None:
    _write_json(
        root / "candidate_selection.json",
        {
            "status": "PASS",
            "selected_candidate": "price_volume_defensive",
            "best_candidate": "price_volume_defensive",
            "results": [
                {
                    "name": "price_volume_defensive",
                    "metrics": {
                        "annualized_return": annual_return,
                        "max_drawdown": max_drawdown,
                        "sharpe_ratio": sharpe,
                    },
                }
            ],
        },
    )
    _write_json(root / "candidate_experiment_readiness.json", {"decision": "PASS"})
    _write_json(
        root / "candidate_experiment_launch.json",
        {"decision": "PASS", "selected_candidate": "price_volume_defensive"},
    )
    _write_json(
        root / "candidate_experiment_completion.json",
        {"decision": "PASS", "selected_candidate": "price_volume_defensive"},
    )
    _write_json(root / "goal" / "capital_goal_status.json", {"decision": "PASS"})
    _write_json(root / "paper_stability.json", {"status": "PASS", "observed_days": 45})
    _write_json(
        root / "approval_record.json",
        {
            "approval_required": True,
            "approved_by": "tester",
            "approved_at": "2026-06-09",
            "approval_notes": "unit test approval record",
        },
    )
    _write_json(root / "first_million_strategy_brief.json", {"decision": "RUN_RESEARCH"})


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
