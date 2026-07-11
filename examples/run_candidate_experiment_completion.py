"""Review whether a launched candidate experiment has complete evidence."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.research.candidate_experiment_completion import (
    build_candidate_experiment_completion,
    write_candidate_experiment_completion,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Review candidate experiment completion.")
    parser.add_argument("--report-dir", required=True, help="Directory with first-million artifacts")
    parser.add_argument("--launch", default=None, help="Optional candidate_experiment_launch.json path")
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    args = parser.parse_args()

    review = build_candidate_experiment_completion(
        args.report_dir,
        launch_path=args.launch,
        as_of=args.as_of,
    )
    out = write_candidate_experiment_completion(review, Path(args.report_dir))
    logger.info("Candidate experiment completion decision: {}", review.decision)
    logger.info("Candidate experiment completion written to {}", out.resolve())
    if review.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
