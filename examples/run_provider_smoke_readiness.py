"""Summarize provider smoke-import viability without changing data gates."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.provider_smoke_readiness import (
    build_provider_smoke_readiness,
    write_provider_smoke_readiness,
)
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Build provider smoke-readiness report.")
    parser.add_argument("--config", default="config/research_recent.yaml", help="Recent A-share config")
    parser.add_argument(
        "--latest-import-report",
        default="results/import/recent/data_import.json",
        help="Provider smoke import report JSON",
    )
    parser.add_argument("--output-dir", default="results/first_million")
    parser.add_argument("--provider", default="akshare")
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument("--min-trading-days", type=int, default=240)
    args = parser.parse_args()

    cfg = load_config(args.config)
    report = build_provider_smoke_readiness(
        latest_import_report_path=args.latest_import_report,
        requested_end=str(cfg.research.end),
        provider=args.provider,
        as_of=args.as_of,
        min_symbols=args.min_symbols,
        min_trading_days=args.min_trading_days,
    )
    out = write_provider_smoke_readiness(report, Path(args.output_dir))
    logger.info("Provider smoke readiness: {}", report.status)
    logger.info("Provider smoke readiness written to {}", out.resolve())
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
