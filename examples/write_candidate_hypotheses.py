"""Write a research-only hypothesis catalog for strategy candidates."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.research.candidate_hypotheses import (
    build_candidate_hypothesis_catalog,
    write_candidate_hypothesis_catalog,
)
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Write strategy candidate hypotheses.")
    parser.add_argument("--config", default="config/research_recent.yaml", help="YAML config path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    args = parser.parse_args()

    cfg = load_config(args.config)
    catalog = build_candidate_hypothesis_catalog(cfg, as_of=args.as_of)
    out = write_candidate_hypothesis_catalog(catalog, Path(args.output_dir))
    logger.info("Candidate hypothesis catalog status: {}", catalog.status)
    logger.info("Candidate hypothesis catalog written to {}", out.resolve())


if __name__ == "__main__":
    main()
