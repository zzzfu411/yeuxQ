"""Build a first-million capital-goal status dashboard from a report directory."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.goal import CapitalGoal, build_capital_goal_status, write_capital_goal_status
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit report evidence against the capital goal.")
    parser.add_argument("--report-dir", required=True, help="Research or weekly pipeline report directory")
    parser.add_argument("--config", default=None, help="Optional YAML config path for cache-health evidence")
    parser.add_argument(
        "--source-qa-dir",
        default=None,
        help="Optional data source QA review directory or data_source_qa_review.json path",
    )
    parser.add_argument(
        "--import-doctor-dir",
        default=None,
        help="Optional data import doctor directory or data_import_doctor.json path",
    )
    parser.add_argument(
        "--offline-intake-dir",
        default=None,
        help="Optional guarded offline intake directory or offline_data_intake.json path",
    )
    parser.add_argument("--starting-capital", type=float, default=100_000.0)
    parser.add_argument("--target-capital", type=float, default=1_000_000.0)
    parser.add_argument("--years", type=float, default=8.0)
    parser.add_argument("--max-drawdown-budget", type=float, default=0.20)
    parser.add_argument("--as-of", default=None, help="Cache-health as-of date YYYY-MM-DD")
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument("--min-trading-days", type=int, default=240)
    args = parser.parse_args()

    goal = CapitalGoal(
        starting_capital=args.starting_capital,
        target_capital=args.target_capital,
        years=args.years,
        max_drawdown_budget=args.max_drawdown_budget,
    )
    cfg = load_config(args.config) if args.config else None
    status = build_capital_goal_status(
        Path(args.report_dir),
        goal=goal,
        cfg=cfg,
        source_qa_dir=args.source_qa_dir,
        import_doctor_dir=args.import_doctor_dir,
        offline_intake_dir=args.offline_intake_dir,
        as_of=args.as_of,
        min_symbols=args.min_symbols,
        min_trading_days=args.min_trading_days,
    )
    out = write_capital_goal_status(status, Path(args.report_dir))
    logger.info("Capital goal status: {}", status.decision)
    logger.info("Capital goal status written to {}", out.resolve())


if __name__ == "__main__":
    main()
