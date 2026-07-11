"""Review stability of a continuous paper-trading state directory.

Usage:
    uv run python examples/run_paper_stability.py --paper-dir results/paper/core
"""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.paper import evaluate_paper_stability, write_paper_stability_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate continuous paper-loop stability.")
    parser.add_argument("--paper-dir", required=True, help="Paper loop state directory")
    parser.add_argument("--output-dir", default=None, help="Defaults to --paper-dir")
    parser.add_argument("--min-observed-days", type=int, default=20)
    parser.add_argument("--target-observed-days", type=int, default=40)
    parser.add_argument("--max-drawdown-watch", type=float, default=0.10)
    parser.add_argument("--max-drawdown-block", type=float, default=0.15)
    parser.add_argument("--max-reject-rate-watch", type=float, default=0.10)
    parser.add_argument("--max-reject-rate-block", type=float, default=0.20)
    parser.add_argument("--max-single-day-loss", type=float, default=0.05)
    args = parser.parse_args()

    report = evaluate_paper_stability(
        args.paper_dir,
        min_observed_days=args.min_observed_days,
        target_observed_days=args.target_observed_days,
        max_drawdown_watch=args.max_drawdown_watch,
        max_drawdown_block=args.max_drawdown_block,
        max_reject_rate_watch=args.max_reject_rate_watch,
        max_reject_rate_block=args.max_reject_rate_block,
        max_single_day_loss=args.max_single_day_loss,
    )
    out = write_paper_stability_report(report, Path(args.output_dir or args.paper_dir))
    logger.info("Paper stability status: {}", report.status)
    logger.info("Paper stability report written to {}", out.resolve())


if __name__ == "__main__":
    main()
