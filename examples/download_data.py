"""Download A-share historical bars into local SQLite cache.

Usage:
    uv run python examples/download_data.py --symbol 600519 \\
        --start 2020-01-01 --end 2025-01-01
"""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.akshare_feed import AkshareFeed
from quantify.data.storage import BarStorage


def main() -> None:
    parser = argparse.ArgumentParser(description="Download A-share daily bars via AKShare.")
    parser.add_argument("--symbol", required=True, help="A-share code, e.g. 600519")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD (inclusive)")
    parser.add_argument(
        "--cache",
        default="./data_cache/quotes.db",
        help="SQLite cache path (default: ./data_cache/quotes.db)",
    )
    parser.add_argument(
        "--adjust",
        default="qfq",
        choices=["", "qfq", "hfq"],
        help="Adjustment: '' raw, 'qfq' forward-adjusted (default), 'hfq' back-adjusted",
    )
    args = parser.parse_args()

    storage = BarStorage(args.cache)
    feed = AkshareFeed(storage=storage, adjust=args.adjust)
    df = feed.fetch(args.symbol, args.start, args.end)

    logger.info("Done. Cached {} rows at {}", len(df), Path(args.cache).resolve())
    if not df.empty:
        logger.info("Date range: {} .. {}", df["date"].iloc[0], df["date"].iloc[-1])
        logger.info("Last bar: {}", df.iloc[-1].to_dict())


if __name__ == "__main__":
    main()
