"""Build a research-only next-experiment queue from blocked candidate evidence."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.research.candidate_next_experiments import (
    build_candidate_next_experiments_report,
    load_candidate_report_bundle,
    write_candidate_next_experiments_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build research-only candidate next experiments.")
    parser.add_argument(
        "--report-dir",
        action="append",
        required=True,
        help="Candidate report directory; pass more than once to merge evidence.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory. Defaults to the first --report-dir.",
    )
    args = parser.parse_args()

    bundles = [load_candidate_report_bundle(path) for path in args.report_dir]
    output_dir = Path(args.output_dir or args.report_dir[0])
    report = build_candidate_next_experiments_report(bundles)
    out = write_candidate_next_experiments_report(report, output_dir)

    logger.info("Candidate next experiments status: {}", report.status)
    logger.info("Promotion decision: {}", report.promotion_decision)
    logger.info("Experiment count: {}", report.experiment_count)
    logger.info("Candidate next experiments written to {}", out.resolve())


if __name__ == "__main__":
    main()
