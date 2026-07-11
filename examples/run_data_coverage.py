"""Analyze per-symbol coverage in the local research cache.

Usage:
    uv run python examples/run_data_coverage.py --config config/research.yaml --output-dir results/research/<timestamp>
"""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.ops import analyze_data_coverage, write_data_coverage_report
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze cached A-share data coverage.")
    parser.add_argument("--config", default="config/research.yaml", help="YAML config path")
    parser.add_argument("--cache", default=None, help="Override config data.cache_path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--min-coverage-ratio", type=float, default=0.95)
    args = parser.parse_args()

    cfg = load_config(args.config)
    provider = DataProvider(BarStorage(args.cache or cfg.data.cache_path))
    report = analyze_data_coverage(
        provider,
        cfg.research.start,
        cfg.research.end,
        min_coverage_ratio=args.min_coverage_ratio,
    )
    out = write_data_coverage_report(report, Path(args.output_dir))
    logger.info("Data coverage status: {}", report.status)
    logger.info("Data coverage written to {}", out.resolve())


if __name__ == "__main__":
    main()
