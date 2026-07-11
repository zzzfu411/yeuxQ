"""Execute a PASS candidate experiment launch plan with guarded logging."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.research.candidate_experiment_execution import (
    run_candidate_experiment_execution,
    write_candidate_experiment_execution,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute guarded candidate experiment commands.")
    parser.add_argument("--report-dir", required=True, help="Directory with first-million artifacts")
    parser.add_argument("--launch", default=None, help="Optional candidate_experiment_launch.json path")
    parser.add_argument("--dry-run", action="store_true", help="Validate commands without executing them")
    args = parser.parse_args()

    report = run_candidate_experiment_execution(
        Path(args.report_dir),
        launch_path=args.launch,
        dry_run=args.dry_run,
    )
    out = write_candidate_experiment_execution(report, Path(args.report_dir))
    logger.info("Candidate experiment execution decision: {}", report.decision)
    logger.info("Candidate experiment execution written to {}", out.resolve())
    if report.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
