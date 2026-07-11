"""Build the daily operator brief for the first-million objective."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.ops.first_million_daily_brief import (
    build_first_million_daily_brief,
    write_first_million_daily_brief,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build first-million daily operator brief.")
    parser.add_argument("--report-dir", default="results/first_million")
    parser.add_argument("--recent-research-dir", default=None)
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    args = parser.parse_args()

    brief = build_first_million_daily_brief(
        args.report_dir,
        as_of=args.as_of,
        recent_research_dir=args.recent_research_dir,
    )
    out = write_first_million_daily_brief(brief, Path(args.report_dir))
    logger.info("First-million daily brief decision: {}", brief.decision)
    logger.info("First-million daily brief written to {}", out.resolve())
    if brief.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
