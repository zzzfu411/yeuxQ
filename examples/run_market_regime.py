"""Detect broad market regime from cached A-share daily bars.

Usage:
    uv run python examples/run_market_regime.py --config config/research.yaml --output-dir results/research/<timestamp>
"""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.market import detect_market_regime, write_market_regime_report
from quantify.research.demo_data import seed_demo_data
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect market regime from local research cache.")
    parser.add_argument("--config", default="config/research.yaml", help="YAML config path")
    parser.add_argument("--cache", default=None, help="Override config data.cache_path")
    parser.add_argument("--output-dir", required=True, help="Output directory for market_regime files")
    parser.add_argument(
        "--symbols",
        default="",
        help="Optional comma-separated symbol list; defaults to the cached research universe.",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    cache_path = args.cache or cfg.data.cache_path
    storage = BarStorage(cache_path)
    provider = DataProvider(storage)
    if not provider.all_symbols() or not provider.trading_days(cfg.research.start, cfg.research.end):
        if not cfg.research.allow_demo_data:
            raise RuntimeError("No cached research data found and allow_demo_data=false.")
        seed_demo_data(storage, cfg.research.start, cfg.research.end)

    symbols = [symbol.strip() for symbol in args.symbols.split(",") if symbol.strip()] or None
    report = detect_market_regime(provider, cfg.research.start, cfg.research.end, symbols=symbols)
    out = write_market_regime_report(report, Path(args.output_dir))
    logger.info("Market regime: {} ({})", report.label, report.status)
    logger.info("Market regime report written to {}", out.resolve())


if __name__ == "__main__":
    main()
