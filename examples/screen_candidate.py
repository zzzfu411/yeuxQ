"""Screen a research report against the first-million capital goal."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from loguru import logger

from quantify.goal import CapitalGoal, build_capital_goal_plan, screen_strategy_candidate, write_goal_plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Screen a strategy candidate for the capital goal.")
    parser.add_argument("--report-dir", required=True, help="Research report directory")
    parser.add_argument("--starting-capital", type=float, default=100_000.0)
    parser.add_argument("--target-capital", type=float, default=1_000_000.0)
    parser.add_argument("--years", type=float, default=5.0)
    parser.add_argument("--max-drawdown-budget", type=float, default=0.20)
    args = parser.parse_args()

    root = Path(args.report_dir)
    goal = CapitalGoal(
        starting_capital=args.starting_capital,
        target_capital=args.target_capital,
        years=args.years,
        max_drawdown_budget=args.max_drawdown_budget,
    )
    plan = build_capital_goal_plan(goal)
    write_goal_plan(plan, root)
    summary = _read_json(root / "summary.json")
    robustness = _read_json(root / "robustness_report.json")
    audit = _read_json(root / "data_audit.json")
    reject_rate = _reject_rate(root / "orders.csv")
    score = screen_strategy_candidate(
        summary,
        goal=goal,
        reject_rate=reject_rate,
        robustness_status=str(robustness.get("status", "UNKNOWN")),
        data_audit_status=str(audit.get("status", "UNKNOWN")),
    )
    (root / "strategy_candidate_score.json").write_text(
        json.dumps(score.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "strategy_candidate_score.md").write_text(_score_markdown(score), encoding="utf-8")
    logger.info("Strategy candidate decision: {}", score.decision)
    logger.info("Strategy candidate score written to {}", (root / "strategy_candidate_score.md").resolve())


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _reject_rate(path: Path) -> float:
    if not path.exists() or path.stat().st_size == 0:
        return 0.0
    orders = pd.read_csv(path)
    if orders.empty or "status" not in orders:
        return 0.0
    return float((orders["status"].astype(str).str.lower() == "rejected").mean())


def _score_markdown(score) -> str:
    lines = [
        f"# Strategy Candidate Score: {score.decision}",
        "",
        f"- Score: {score.score:.1f}",
        "",
        "## Metrics",
    ]
    lines.extend(f"- {key}: `{value}`" for key, value in score.metrics.items())
    lines.extend(["", "## Reasons"])
    lines.extend(f"- {reason}" for reason in score.reasons)
    lines.extend(
        [
            "",
            "This score is a research gate. It is not a promise of profit and not a live trading instruction.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
