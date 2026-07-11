"""Plan whether a selected candidate can enter continuous paper observation."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.paper import build_paper_candidate_plan, write_paper_candidate_plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a candidate-to-paper observation plan.")
    parser.add_argument("--report-dir", required=True, help="Research or weekly pipeline report directory")
    parser.add_argument("--config", default="config/research_recent.yaml", help="YAML config for paper loop command")
    parser.add_argument("--paper-state-dir", default="results/paper/core", help="Persistent paper state directory")
    parser.add_argument("--candidate", default=None, help="Override candidate name; defaults to best_candidate")
    args = parser.parse_args()

    plan = build_paper_candidate_plan(
        Path(args.report_dir),
        config_path=args.config,
        paper_state_dir=args.paper_state_dir,
        candidate=args.candidate,
    )
    out = write_paper_candidate_plan(plan, Path(args.report_dir))
    logger.info("Paper candidate plan decision: {}", plan.decision)
    logger.info("Paper candidate plan written to {}", out.resolve())
    if plan.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
