"""Validate offline CSV research data before importing it into SQLite."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.csv_contract import validate_research_csvs, write_csv_validation_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate offline research CSV files.")
    parser.add_argument("--bars-csv", required=True, help="Bars CSV path")
    parser.add_argument("--stock-info-csv", default=None, help="Optional stock_info CSV path")
    parser.add_argument("--fundamentals-csv", default=None, help="Optional fundamentals CSV path")
    parser.add_argument("--calendar-csv", default=None, help="Optional trading calendar CSV path")
    parser.add_argument("--suspensions-csv", default=None, help="Optional suspensions CSV path")
    parser.add_argument("--index-constituents-csv", default=None, help="Optional index constituents CSV path")
    parser.add_argument("--start", default=None, help="Expected research start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="Expected research end date YYYY-MM-DD")
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument("--encoding", default="utf-8-sig", help="CSV encoding, e.g. auto, utf-8-sig, or gbk")
    parser.add_argument("--output-dir", default="results/import/csv_validation")
    args = parser.parse_args()

    try:
        report = validate_research_csvs(
            bars_csv=args.bars_csv,
            stock_info_csv=args.stock_info_csv,
            fundamentals_csv=args.fundamentals_csv,
            calendar_csv=args.calendar_csv,
            suspensions_csv=args.suspensions_csv,
            index_constituents_csv=args.index_constituents_csv,
            start=args.start,
            end=args.end,
            min_symbols=args.min_symbols,
            encoding=args.encoding,
        )
    except ValueError as exc:
        logger.error("{}", exc)
        raise SystemExit(2) from exc
    out = write_csv_validation_report(report, Path(args.output_dir))
    logger.info("CSV validation status: {}", report.status)
    logger.info("CSV validation report written to {}", out.resolve())
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
