"""Advance a recoverable daily paper-trading loop.

Usage:
    uv run python examples/run_paper_loop.py --config config/research.yaml --state-dir results/paper/core
"""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.paper import evaluate_paper_stability, run_paper_loop, write_paper_stability_report
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Advance a local daily paper loop.")
    parser.add_argument("--config", default="config/research.yaml", help="YAML config path")
    parser.add_argument("--cache", default=None, help="Override config data.cache_path")
    parser.add_argument("--state-dir", required=True, help="Persistent paper state directory")
    parser.add_argument("--start", default=None, help="Run start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="Run end date YYYY-MM-DD")
    parser.add_argument("--candidate", default=None, help="Candidate strategy name")
    parser.add_argument("--initial-cash", type=float, default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    provider = DataProvider(BarStorage(args.cache or cfg.data.cache_path))
    result = run_paper_loop(
        provider,
        cfg,
        state_dir=Path(args.state_dir),
        start=args.start,
        end=args.end,
        candidate=args.candidate,
        initial_cash=args.initial_cash,
    )
    logger.info("Paper loop as_of: {}", result.state.as_of)
    logger.info("Paper loop observed days: {}", result.state.observed_days)
    logger.info("Paper loop new days: {}", len(result.run_days))
    stability = evaluate_paper_stability(args.state_dir)
    write_paper_stability_report(stability, Path(args.state_dir))
    logger.info("Paper stability status: {}", stability.status)
    logger.info("Paper loop state written to {}", Path(args.state_dir).resolve())


if __name__ == "__main__":
    main()
