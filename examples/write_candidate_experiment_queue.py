"""Write a pre-registered experiment queue for strategy candidates."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.research.candidate_experiment_queue import (
    build_candidate_experiment_queue,
    write_candidate_experiment_queue,
)
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Write strategy candidate experiment queue.")
    parser.add_argument("--config", default="config/research_recent.yaml", help="YAML config path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    args = parser.parse_args()

    cfg = load_config(args.config)
    queue = build_candidate_experiment_queue(cfg, as_of=args.as_of)
    out = write_candidate_experiment_queue(queue, Path(args.output_dir))
    logger.info("Candidate experiment queue status: {}", queue.status)
    logger.info("Candidate experiment queue written to {}", out.resolve())


if __name__ == "__main__":
    main()
