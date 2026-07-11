from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.goal import CapitalGoal, build_capital_goal_plan, screen_strategy_candidate, write_goal_plan
from quantify.market import MarketRegimeNote, write_market_regime_note


def test_capital_goal_plan_quantifies_required_return(tmp_path: Path) -> None:
    goal = CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=5)
    plan = build_capital_goal_plan(goal)
    out = write_goal_plan(plan, tmp_path)

    assert plan.status == "BLOCK"
    assert goal.required_annual_return() > 0.35
    assert (out / "capital_goal_plan.json").exists()
    assert "Required annual return" in (out / "capital_goal_plan.md").read_text(encoding="utf-8")


def test_strategy_candidate_screen_warns_when_return_below_goal() -> None:
    goal = CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8)

    score = screen_strategy_candidate(
        {"annualized_return": 0.10, "max_drawdown": 0.08, "sharpe_ratio": 1.0},
        goal=goal,
        reject_rate=0.0,
        robustness_status="PASS",
        data_audit_status="PASS",
    )

    assert score.decision == "WATCH"
    assert any("below the required" in reason for reason in score.reasons)


def test_strategy_candidate_blocks_bad_audit() -> None:
    goal = CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8)

    score = screen_strategy_candidate(
        {"annualized_return": 0.35, "max_drawdown": 0.08, "sharpe_ratio": 1.0},
        goal=goal,
        reject_rate=0.0,
        robustness_status="PASS",
        data_audit_status="BLOCK",
    )

    assert score.decision == "BLOCK"


def test_market_regime_note_writes_warning_artifacts(tmp_path: Path) -> None:
    note = MarketRegimeNote(
        as_of="2026-06-08",
        market="A-share daily",
        summary="Uneven market.",
        assumptions=["No single theme concentration."],
        strategy_implications=["Use diversified low-frequency research."],
        risk_warnings=["No guaranteed profit."],
    )
    out = write_market_regime_note(note, tmp_path)

    assert (out / "market_regime.json").exists()
    assert "No guaranteed profit" in (out / "market_regime.md").read_text(encoding="utf-8")


def test_screen_candidate_cli_writes_score(tmp_path: Path) -> None:
    (tmp_path / "summary.json").write_text(
        json.dumps(
            {
                "annualized_return": 0.10,
                "max_drawdown": 0.08,
                "sharpe_ratio": 1.0,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "data_audit.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    (tmp_path / "robustness_report.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    pd.DataFrame({"status": ["filled", "filled"]}).to_csv(tmp_path / "orders.csv", index=False)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/screen_candidate.py",
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

    assert completed.returncode == 0
    score = json.loads((tmp_path / "strategy_candidate_score.json").read_text(encoding="utf-8"))
    assert score["decision"] == "WATCH"
