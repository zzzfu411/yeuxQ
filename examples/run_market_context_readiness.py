"""Review market context evidence for candidate research readiness."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.market import (
    build_market_context_readiness_from_report,
    write_market_context_readiness,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Review market context evidence readiness.")
    parser.add_argument("--report-dir", default="results/first_million")
    parser.add_argument("--as-of", default=None, help="Target evidence as-of date YYYY-MM-DD")
    parser.add_argument("--max-staleness-days", type=int, default=7)
    args = parser.parse_args()

    readiness = build_market_context_readiness_from_report(
        args.report_dir,
        as_of=args.as_of,
        max_staleness_days=args.max_staleness_days,
    )
    out = write_market_context_readiness(readiness, Path(args.report_dir))
    logger.info("Market context readiness: {}", readiness.decision)
    logger.info("Market context readiness written to {}", out.resolve())
    if readiness.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
