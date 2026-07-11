"""Build an explicit symbol file from AKShare/CSIndex index constituents."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.akshare_universe import build_akshare_index_universe


def main() -> None:
    parser = argparse.ArgumentParser(description="Build AKShare index-constituent symbol file.")
    parser.add_argument("--index-code", default="000906", help="CSIndex code, e.g. 000906 for CSI 800")
    parser.add_argument("--limit", type=int, default=300, help="Number of symbols to write; 0 means all")
    parser.add_argument("--output-dir", default="results/import/akshare_universe")
    parser.add_argument(
        "--selection-method",
        choices=["stratified_exchange", "provider_order", "symbol"],
        default="stratified_exchange",
        help="How to select a limited subset from the current constituents.",
    )
    args = parser.parse_args()

    report = build_akshare_index_universe(
        index_code=args.index_code,
        limit=args.limit,
        output_dir=Path(args.output_dir),
        selection_method=args.selection_method,
    )
    logger.info("AKShare universe status: {}", report.status)
    logger.info("Symbols written: {}", report.symbol_count)
    logger.info("Symbol file: {}", Path(report.symbol_file).resolve())
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
