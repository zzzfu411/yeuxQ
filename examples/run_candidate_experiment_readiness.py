"""Review whether pre-registered candidate experiments may run."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.research.candidate_experiment_readiness import (
    build_candidate_experiment_readiness_from_report,
    write_candidate_experiment_readiness,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Review candidate experiment readiness.")
    parser.add_argument("--report-dir", required=True, help="Directory with first-million artifacts")
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    args = parser.parse_args()

    readiness = build_candidate_experiment_readiness_from_report(args.report_dir, as_of=args.as_of)
    out = write_candidate_experiment_readiness(readiness, Path(args.report_dir))
    logger.info("Candidate experiment readiness decision: {}", readiness.decision)
    logger.info("Candidate experiment readiness written to {}", out.resolve())


if __name__ == "__main__":
    main()
