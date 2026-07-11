"""Review strategy registry candidates against a capital goal.

Usage:
    uv run python examples/review_strategy_promotions.py --registry results/strategy_registry/strategy_registry.json --output-dir results/strategy_registry
"""
from __future__ import annotations

import argparse

from loguru import logger

from quantify.goal import CapitalGoal
from quantify.ops import review_strategy_promotions, write_strategy_promotion_review


def main() -> None:
    parser = argparse.ArgumentParser(description="Review strategy promotion candidates.")
    parser.add_argument("--registry", default="results/strategy_registry/strategy_registry.json")
    parser.add_argument("--output-dir", default="results/strategy_registry")
    parser.add_argument("--starting-capital", type=float, default=100_000.0)
    parser.add_argument("--target-capital", type=float, default=1_000_000.0)
    parser.add_argument("--years", type=float, default=8.0)
    parser.add_argument("--max-drawdown-budget", type=float, default=0.20)
    args = parser.parse_args()

    goal = CapitalGoal(
        starting_capital=args.starting_capital,
        target_capital=args.target_capital,
        years=args.years,
        max_drawdown_budget=args.max_drawdown_budget,
    )
    write_strategy_promotion_review(args.registry, args.output_dir, goal=goal)
    review = review_strategy_promotions(args.registry, goal=goal)
    logger.info("Strategy promotion review decision: {}", review.decision)


if __name__ == "__main__":
    main()
