"""Write a pre-registered candidate experiment design matrix."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.research.candidate_experiment_design import (
    build_candidate_experiment_design_matrix,
    write_candidate_experiment_design_matrix,
)
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write pre-registered candidate experiment design matrix."
    )
    parser.add_argument("--config", default="config/research_recent.yaml", help="YAML config path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    args = parser.parse_args()

    cfg = load_config(args.config)
    matrix = build_candidate_experiment_design_matrix(cfg, as_of=args.as_of)
    out = write_candidate_experiment_design_matrix(matrix, Path(args.output_dir))
    logger.info("Candidate experiment design matrix status: {}", matrix.status)
    logger.info("Candidate experiment design matrix rows: {}", matrix.scenario_count)
    logger.info("Candidate experiment design matrix written to {}", out.resolve())


if __name__ == "__main__":
    main()
