"""Verify cached A-share data is recent real-data evidence.

Usage:
    uv run python examples/run_real_data_gate.py --config config/research.yaml --output-dir results/research/<timestamp>
"""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.ops import evaluate_real_data_gate, write_real_data_gate
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run real-data recency and coverage gate.")
    parser.add_argument("--config", default="config/research.yaml", help="YAML config path")
    parser.add_argument("--cache", default=None, help="Override config data.cache_path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--as-of", default=None, help="Gate as-of date YYYY-MM-DD")
    parser.add_argument("--min-symbols", type=int, default=50)
    parser.add_argument("--min-trading-days", type=int, default=120)
    parser.add_argument("--max-staleness-days", type=int, default=10)
    args = parser.parse_args()

    cfg = load_config(args.config)
    provider = DataProvider(BarStorage(args.cache or cfg.data.cache_path))
    result = evaluate_real_data_gate(
        provider,
        cfg.research.start,
        cfg.research.end,
        as_of=args.as_of,
        min_symbols=args.min_symbols,
        min_trading_days=args.min_trading_days,
        max_staleness_days=args.max_staleness_days,
    )
    out = write_real_data_gate(result, Path(args.output_dir))
    logger.info("Real data gate decision: {}", result.decision)
    logger.info("Real data gate written to {}", out.resolve())


if __name__ == "__main__":
    main()
