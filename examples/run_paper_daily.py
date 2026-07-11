"""Create paper-trading daily review artifacts from a research report."""
from __future__ import annotations

import argparse

from loguru import logger

from quantify.paper import write_paper_daily_review


def main() -> None:
    parser = argparse.ArgumentParser(description="Write paper daily review artifacts.")
    parser.add_argument("--report-dir", required=True, help="Research report directory")
    parser.add_argument("--output-dir", default=None, help="Output directory; defaults to report-dir")
    args = parser.parse_args()
    out = write_paper_daily_review(args.report_dir, args.output_dir)
    logger.info("Paper daily review written to {}", out.resolve())


if __name__ == "__main__":
    main()
