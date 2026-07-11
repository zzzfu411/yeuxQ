"""Evaluate whether capital may be increased after paper/readiness evidence."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.readiness import build_capital_scaling_plan, write_capital_scaling_plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a gradual capital scaling plan.")
    parser.add_argument("--report-dir", required=True, help="Report directory with readiness evidence")
    parser.add_argument("--current-capital", type=float, required=True)
    parser.add_argument("--proposed-capital", type=float, required=True)
    parser.add_argument("--max-increment-pct", type=float, default=0.25)
    parser.add_argument("--min-paper-days", type=int, default=40)
    args = parser.parse_args()

    plan = build_capital_scaling_plan(
        Path(args.report_dir),
        current_capital=args.current_capital,
        proposed_capital=args.proposed_capital,
        max_increment_pct=args.max_increment_pct,
        min_paper_days=args.min_paper_days,
    )
    out = write_capital_scaling_plan(plan, Path(args.report_dir))
    logger.info("Capital scaling decision: {}", plan.decision)
    logger.info("Capital scaling plan written to {}", out.resolve())


if __name__ == "__main__":
    main()
