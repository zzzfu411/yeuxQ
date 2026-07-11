"""Build a manual target portfolio plan from local research data.

Usage:
    uv run python examples/run_target_plan.py --config config/research.yaml --output-dir results/target_plan
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from loguru import logger

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.readiness import build_manual_target_plan, write_manual_target_plan
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Build manual target portfolio reference files.")
    parser.add_argument("--config", default="config/research.yaml", help="YAML config path")
    parser.add_argument("--cache", default=None, help="Override config data.cache_path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--as-of", default=None, help="Plan date YYYY-MM-DD; defaults to latest cached day")
    parser.add_argument("--candidate", default=None, help="Candidate strategy name")
    parser.add_argument("--capital", type=float, default=None, help="Manual planning capital")
    parser.add_argument("--cash-buffer-pct", type=float, default=0.05)
    parser.add_argument("--current-positions", default=None, help="Optional paper_positions.csv path")
    args = parser.parse_args()

    cfg = load_config(args.config)
    provider = DataProvider(BarStorage(args.cache or cfg.data.cache_path))
    current_positions = _read_positions(args.current_positions)
    plan = build_manual_target_plan(
        provider,
        cfg,
        as_of=args.as_of,
        candidate=args.candidate,
        capital=args.capital,
        cash_buffer_pct=args.cash_buffer_pct,
        current_positions=current_positions,
    )
    out = write_manual_target_plan(plan, Path(args.output_dir))
    logger.info("Manual target plan candidate: {}", plan.candidate)
    logger.info("Manual target plan rows: {}", plan.target_count)
    logger.info("Manual target plan written to {}", out.resolve())


def _read_positions(path: str | None) -> pd.DataFrame | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return None
    return pd.read_csv(p)


if __name__ == "__main__":
    main()
