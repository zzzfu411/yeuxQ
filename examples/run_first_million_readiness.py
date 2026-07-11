"""Write a single-screen readiness card for first-million evidence."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.ops.first_million_readiness import (
    build_first_million_readiness_card,
    write_first_million_readiness_card,
)
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Write first-million readiness card.")
    parser.add_argument("--report-dir", default="results/first_million")
    parser.add_argument("--config", default=None, help="Optional recent A-share config for live cache evidence")
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument("--min-trading-days", type=int, default=240)
    args = parser.parse_args()

    cfg = load_config(args.config) if args.config else None
    card = build_first_million_readiness_card(
        args.report_dir,
        as_of=args.as_of,
        cfg=cfg,
        min_symbols=args.min_symbols,
        min_trading_days=args.min_trading_days,
    )
    out = write_first_million_readiness_card(card, Path(args.report_dir))
    logger.info("First-million readiness decision: {}", card.decision)
    logger.info("First-million readiness written to {}", out.resolve())
    if card.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
