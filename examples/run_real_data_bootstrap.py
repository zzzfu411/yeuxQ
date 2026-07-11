"""Check whether the local A-share research cache is ready for weekly runs.

Usage:
    uv run python examples/run_real_data_bootstrap.py --config config/research.yaml --output-dir results/bootstrap
"""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.ops import build_real_data_bootstrap_report, write_real_data_bootstrap_report
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a real-data bootstrap readiness checklist.")
    parser.add_argument("--config", default="config/research.yaml", help="YAML config path")
    parser.add_argument("--cache", default=None, help="Override config data.cache_path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--as-of", default=None, help="Gate as-of date YYYY-MM-DD")
    parser.add_argument("--min-symbols", type=int, default=50)
    parser.add_argument("--min-trading-days", type=int, default=120)
    parser.add_argument("--max-staleness-days", type=int, default=10)
    parser.add_argument("--min-coverage-ratio", type=float, default=0.95)
    args = parser.parse_args()

    cfg = load_config(args.config)
    cache_path = Path(args.cache or cfg.data.cache_path)
    cache_exists_before_open = cache_path.exists()
    cache_size_before_open = cache_path.stat().st_size if cache_exists_before_open else 0
    provider = DataProvider(BarStorage(cache_path))
    report = build_real_data_bootstrap_report(
        provider,
        cfg,
        config_path=args.config,
        cache_path=cache_path,
        as_of=args.as_of,
        min_symbols=args.min_symbols,
        min_trading_days=args.min_trading_days,
        max_staleness_days=args.max_staleness_days,
        min_coverage_ratio=args.min_coverage_ratio,
        cache_exists_before_open=cache_exists_before_open,
        cache_size_before_open=cache_size_before_open,
    )
    out = write_real_data_bootstrap_report(report, Path(args.output_dir))
    logger.info("Real-data bootstrap decision: {}", report.decision)
    logger.info("Real-data bootstrap report written to {}", out.resolve())


if __name__ == "__main__":
    main()
