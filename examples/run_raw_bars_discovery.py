"""Discover local raw broker/vendor daily bars CSV files."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.raw_bars_discovery import (
    build_raw_bars_discovery_report,
    write_raw_bars_discovery_report,
    write_raw_bars_dropzone_kit,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover raw broker/vendor A-share daily bars CSV files.")
    parser.add_argument(
        "--search-dir",
        action="append",
        default=None,
        help="Directory or CSV file to scan. Can be supplied multiple times.",
    )
    parser.add_argument("--config", default="config/research_recent.yaml", help="Recent A-share config")
    parser.add_argument("--output-dir", default="results/first_million")
    parser.add_argument("--data-output-dir", default="data_exports")
    parser.add_argument("--pattern", default="*.csv")
    parser.add_argument("--encoding", default="auto")
    parser.add_argument("--min-symbols", type=int, default=None)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--max-files", type=int, default=50)
    parser.add_argument(
        "--dropzone-dir",
        default=None,
        help="Directory for retained raw broker/vendor daily-bars exports; defaults to <data-output-dir>/raw.",
    )
    parser.add_argument(
        "--write-dropzone-kit",
        action="store_true",
        help="Write README_raw_bars_dropzone.md and create the raw/evidence dropzone directories.",
    )
    args = parser.parse_args()
    dropzone_dir = Path(args.dropzone_dir) if args.dropzone_dir else Path(args.data_output_dir) / "raw"
    if args.write_dropzone_kit:
        dropzone_dir.mkdir(parents=True, exist_ok=True)
        (Path(args.data_output_dir) / "source_qa_evidence").mkdir(parents=True, exist_ok=True)

    report = build_raw_bars_discovery_report(
        search_dirs=args.search_dir,
        config_path=args.config,
        output_dir=args.output_dir,
        data_output_dir=args.data_output_dir,
        pattern=args.pattern,
        encoding=args.encoding,
        min_symbols=args.min_symbols,
        start=args.start,
        end=args.end,
        max_files=args.max_files,
        dropzone_dir=dropzone_dir,
    )
    out = write_raw_bars_discovery_report(report, Path(args.output_dir))
    if args.write_dropzone_kit:
        readme = write_raw_bars_dropzone_kit(report)
        logger.info("Raw bars dropzone kit written to {}", readme.resolve())
    logger.info("Raw bars discovery status: {}", report.status)
    logger.info("Raw bars discovery written to {}", out.resolve())
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
