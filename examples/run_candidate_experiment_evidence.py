"""Copy foundational evidence into a candidate experiment directory."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger

from quantify.research.candidate_experiment_evidence import (
    sync_candidate_experiment_evidence,
    write_candidate_experiment_evidence,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync candidate experiment foundational evidence.")
    parser.add_argument("--source-report-dir", required=True, help="Weekly or first-million report directory")
    parser.add_argument("--output-dir", required=True, help="Candidate experiment directory")
    args = parser.parse_args()

    report = sync_candidate_experiment_evidence(
        source_report_dir=Path(args.source_report_dir),
        output_dir=Path(args.output_dir),
    )
    out = write_candidate_experiment_evidence(report, Path(args.output_dir))
    logger.info("Candidate experiment evidence status: {}", report.status)
    logger.info("Candidate experiment evidence written to {}", out.resolve())
    if report.status == "BLOCK":
        sys.exit(2)


if __name__ == "__main__":
    main()
