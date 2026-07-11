"""Append one report directory to the long-term strategy candidate registry.

Usage:
    uv run python examples/update_strategy_registry.py --report-dir results/research/<timestamp>
"""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.ops import update_candidate_registry


def main() -> None:
    parser = argparse.ArgumentParser(description="Update strategy candidate registry.")
    parser.add_argument("--report-dir", required=True, help="Report directory containing candidate_selection.json")
    parser.add_argument(
        "--registry",
        default="results/strategy_registry/strategy_registry.json",
        help="Path to persistent strategy registry JSON",
    )
    args = parser.parse_args()

    report = update_candidate_registry(args.report_dir, registry_path=Path(args.registry))
    logger.info("Strategy registry candidates: {}", report.candidate_count)
    logger.info("Strategy registry written to {}", Path(report.registry_path).resolve())


if __name__ == "__main__":
    main()
