"""Discover local TongDaXin .day files for recent A-share OHLCV intake."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.tdx_discovery import (
    build_tdx_day_discovery_report,
    write_tdx_day_discovery_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover local TongDaXin .day data.")
    parser.add_argument(
        "--search-dir",
        action="append",
        default=None,
        help="Directory to scan. Can be supplied multiple times. Defaults to common TDX paths.",
    )
    parser.add_argument("--config", default="config/research_recent.yaml", help="Recent A-share config")
    parser.add_argument("--output-dir", default="results/first_million")
    parser.add_argument("--data-output-dir", default="data_exports")
    parser.add_argument("--min-symbols", type=int, default=None)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--as-of", default=None, help="Optional evidence as-of date YYYY-MM-DD")
    parser.add_argument("--max-files-to-probe", type=int, default=2000)
    args = parser.parse_args()

    report = build_tdx_day_discovery_report(
        search_dirs=args.search_dir,
        config_path=args.config,
        output_dir=args.output_dir,
        data_output_dir=args.data_output_dir,
        min_symbols=args.min_symbols,
        start=args.start,
        end=args.end,
        as_of=args.as_of,
        max_files_to_probe=args.max_files_to_probe,
    )
    out = write_tdx_day_discovery_report(report, Path(args.output_dir))
    logger.info("TongDaXin day discovery status: {}", report.status)
    logger.info("TongDaXin day discovery written to {}", out.resolve())
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
