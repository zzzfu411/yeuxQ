"""Build a weekly operating review from existing report artifacts.

Usage:
    uv run python examples/run_weekly_review.py --report-dir results/research/<timestamp>
"""
from __future__ import annotations

import argparse

from loguru import logger

from quantify.ops import build_weekly_review, write_weekly_review


def main() -> None:
    parser = argparse.ArgumentParser(description="Build weekly quant operating review.")
    parser.add_argument("--report-dir", required=True, help="Research/report artifact directory")
    parser.add_argument("--as-of", default=None, help="Optional review date, YYYY-MM-DD")
    args = parser.parse_args()

    out = write_weekly_review(args.report_dir, as_of=args.as_of)
    review = build_weekly_review(out, as_of=args.as_of)
    logger.info("Weekly review decision: {}", review.decision)
    logger.info("Weekly review written to {}", out.resolve())


if __name__ == "__main__":
    main()
