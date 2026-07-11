"""Write a guarded launch plan for the next candidate experiment."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.research.candidate_experiment_launch import (
    build_candidate_experiment_launch_from_report,
    write_candidate_experiment_launch,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Write candidate experiment launch plan.")
    parser.add_argument("--report-dir", required=True, help="Directory with first-million artifacts")
    parser.add_argument("--config", default="config/research_recent.yaml", help="YAML config path")
    parser.add_argument("--candidate", default=None, help="Optional candidate name override")
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    parser.add_argument("--run-id", default=None, help="Optional stable experiment run id")
    args = parser.parse_args()

    plan = build_candidate_experiment_launch_from_report(
        args.report_dir,
        config_path=args.config,
        candidate=args.candidate,
        as_of=args.as_of,
        run_id=args.run_id,
    )
    out = write_candidate_experiment_launch(plan, Path(args.report_dir))
    logger.info("Candidate experiment launch decision: {}", plan.decision)
    logger.info("Candidate experiment launch written to {}", out.resolve())
    if plan.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
