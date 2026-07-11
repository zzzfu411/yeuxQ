"""Build a research-only rollup over recent candidate experiment outputs."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.ops.recent_candidate_research import (
    build_recent_candidate_research_report,
    write_recent_candidate_research_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build recent candidate research rollup.")
    parser.add_argument("--search-dir", default="results/research_recent")
    parser.add_argument("--output-dir", default="results/first_million")
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    parser.add_argument(
        "--max-report-dirs",
        type=int,
        default=24,
        help="Maximum recent report directories to include.",
    )
    args = parser.parse_args()

    report = build_recent_candidate_research_report(
        args.search_dir,
        as_of=args.as_of,
        max_report_dirs=args.max_report_dirs,
    )
    out = write_recent_candidate_research_report(report, Path(args.output_dir))
    logger.info("Recent candidate research best candidate: {}", report.best_research_candidate or "none")
    logger.info("Recent candidate research written to {}", out.resolve())


if __name__ == "__main__":
    main()
