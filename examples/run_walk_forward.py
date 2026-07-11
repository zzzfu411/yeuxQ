"""Run walk-forward validation for the baseline multi-factor strategy.

Usage:
    uv run python examples/run_walk_forward.py --config config/research.yaml --output-dir results/research/<timestamp>
"""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.research.demo_data import seed_demo_data
from quantify.research.walk_forward import run_walk_forward, write_walk_forward_report
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run walk-forward validation.")
    parser.add_argument("--config", default="config/research.yaml", help="YAML config path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--train-days", type=int, default=120)
    parser.add_argument("--test-days", type=int, default=60)
    parser.add_argument("--step-days", type=int, default=60)
    args = parser.parse_args()

    cfg = load_config(args.config)
    storage = BarStorage(cfg.data.cache_path)
    provider = DataProvider(storage)
    if not provider.all_symbols() or not provider.trading_days(cfg.research.start, cfg.research.end):
        if not cfg.research.allow_demo_data:
            raise RuntimeError("No cached research data found and allow_demo_data=false.")
        seed_demo_data(storage, cfg.research.start, cfg.research.end)
    report = run_walk_forward(
        provider,
        cfg,
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
    )
    out = write_walk_forward_report(report, Path(args.output_dir))
    logger.info("Walk-forward status: {}", report.status)
    logger.info("Walk-forward report written to {}", out.resolve())


if __name__ == "__main__":
    main()
