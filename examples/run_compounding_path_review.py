"""Review whether current evidence supports the first-million compounding path."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.goal import CapitalGoal, build_compounding_path_review, write_compounding_path_review


def main() -> None:
    parser = argparse.ArgumentParser(description="Write compounding-path review.")
    parser.add_argument("--report-dir", default="results/first_million")
    parser.add_argument("--starting-capital", type=float, default=100_000.0)
    parser.add_argument("--target-capital", type=float, default=1_000_000.0)
    parser.add_argument("--years", type=float, default=8.0)
    parser.add_argument("--max-drawdown-budget", type=float, default=0.20)
    parser.add_argument("--min-paper-days", type=int, default=40)
    args = parser.parse_args()

    goal = CapitalGoal(
        starting_capital=args.starting_capital,
        target_capital=args.target_capital,
        years=args.years,
        max_drawdown_budget=args.max_drawdown_budget,
    )
    review = build_compounding_path_review(
        args.report_dir,
        goal=goal,
        min_paper_days=args.min_paper_days,
    )
    out = write_compounding_path_review(review, Path(args.report_dir) / "goal")
    logger.info("Compounding path review decision: {}", review.decision)
    logger.info("Compounding path review written to {}", out.resolve())
    if review.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
