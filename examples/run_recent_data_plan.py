"""Build a local plan for acquiring recent A-share research data.

Usage:
    uv run python examples/run_recent_data_plan.py --config config/research_recent.yaml --output-dir results/bootstrap_recent
"""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.acquisition_plan import (
    build_recent_data_acquisition_plan_from_config,
    write_recent_data_acquisition_plan,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan recent A-share data acquisition.")
    parser.add_argument("--config", default="config/research_recent.yaml", help="YAML config path")
    parser.add_argument("--cache", default=None, help="Override config data.cache_path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--as-of", default=None, help="Gate as-of date YYYY-MM-DD")
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument("--import-limit", type=int, default=500)
    parser.add_argument(
        "--latest-import-report",
        default="results/import/recent/data_import.json",
        help="Optional AKShare import attempt report to summarize in the plan",
    )
    args = parser.parse_args()

    plan = build_recent_data_acquisition_plan_from_config(
        config_path=args.config,
        cache_path=args.cache,
        as_of=args.as_of,
        min_symbols=args.min_symbols,
        import_limit=args.import_limit,
        latest_import_report_path=args.latest_import_report,
    )
    out = write_recent_data_acquisition_plan(plan, Path(args.output_dir))
    logger.info("Recent data acquisition plan status: {}", plan.status)
    logger.info("Recent data acquisition plan written to {}", out.resolve())


if __name__ == "__main__":
    main()
