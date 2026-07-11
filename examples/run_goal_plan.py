"""Create a capital goal plan for the first million target."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.goal import CapitalGoal, build_capital_goal_plan, write_goal_plan
from quantify.market import MarketRegimeNote, write_market_regime_note


def main() -> None:
    parser = argparse.ArgumentParser(description="Build capital goal and market regime artifacts.")
    parser.add_argument("--output-dir", default="results/goal", help="Output directory")
    parser.add_argument("--starting-capital", type=float, default=100_000.0)
    parser.add_argument("--target-capital", type=float, default=1_000_000.0)
    parser.add_argument("--years", type=float, default=5.0)
    parser.add_argument("--max-drawdown-budget", type=float, default=0.20)
    args = parser.parse_args()

    goal = CapitalGoal(
        target_capital=args.target_capital,
        starting_capital=args.starting_capital,
        years=args.years,
        max_drawdown_budget=args.max_drawdown_budget,
    )
    out = Path(args.output_dir)
    plan = build_capital_goal_plan(goal)
    write_goal_plan(plan, out)
    write_market_regime_note(_current_a_share_note(), out)
    logger.info("Capital goal status: {}", plan.status)
    logger.info("Goal artifacts written to {}", out.resolve())


def _current_a_share_note() -> MarketRegimeNote:
    return MarketRegimeNote(
        as_of="2026-06-08",
        market="A-share daily",
        summary=(
            "Recent A-share trading has shown index-level hesitation with stronger swings in growth "
            "and technology segments. Treat hot themes as research context, not as direct buy signals."
        ),
        assumptions=[
            "Market regime is uneven rather than broad-based trending.",
            "Single-theme concentration is not suitable for a stable compounding workflow.",
            "Low-frequency, diversified, cost-aware strategies are preferred for first-capital goals.",
        ],
        strategy_implications=[
            "Prefer multi-factor selection with liquidity and low-volatility controls.",
            "Require out-of-sample, cost stress, and paper-trading evidence before promotion.",
            "Use market regime notes as constraints, not as alpha signals.",
        ],
        risk_warnings=[
            "No system can guarantee stable profits or a one-million outcome.",
            "Avoid leverage and avoid increasing capital after a single lucky backtest.",
            "Any BLOCK gate must stop promotion immediately.",
        ],
    )


if __name__ == "__main__":
    main()
