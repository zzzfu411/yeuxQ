"""Discover local index CSV files for market context snapshots."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.market import (
    build_market_index_discovery_report,
    write_market_index_discovery_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover local broad A-share index CSV files.")
    parser.add_argument("--search-dir", action="append", default=[], help="Directory or CSV file to scan")
    parser.add_argument("--output-dir", default="results/first_million")
    parser.add_argument("--as-of", required=True, help="Snapshot as-of date YYYY-MM-DD")
    parser.add_argument("--pattern", default="*.csv")
    parser.add_argument("--encoding", default="auto")
    parser.add_argument("--max-files", type=int, default=50)
    args = parser.parse_args()

    report = build_market_index_discovery_report(
        search_dirs=args.search_dir or None,
        output_dir=args.output_dir,
        as_of=args.as_of,
        pattern=args.pattern,
        encoding=args.encoding,
        max_files=args.max_files,
    )
    out = write_market_index_discovery_report(report, Path(args.output_dir))
    logger.info("Market index discovery status: {}", report.status)
    logger.info("Market index discovery written to {}", out.resolve())
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
