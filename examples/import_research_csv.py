"""Import local CSV research data into SQLite cache."""
from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from loguru import logger

from quantify.data.csv_contract import validate_research_csvs, write_csv_validation_report
from quantify.data.csv_research_importer import import_research_csvs
from quantify.data.research_importer import write_import_report
from quantify.data.storage import BarStorage


def main() -> None:
    parser = argparse.ArgumentParser(description="Import local CSV research data.")
    parser.add_argument("--cache", required=True, help="SQLite cache path")
    parser.add_argument("--bars-csv", required=True, help="Bars CSV path")
    parser.add_argument("--stock-info-csv", default=None, help="Optional stock_info CSV path")
    parser.add_argument("--fundamentals-csv", default=None, help="Optional fundamentals CSV path")
    parser.add_argument("--calendar-csv", default=None, help="Optional trading calendar CSV path")
    parser.add_argument("--suspensions-csv", default=None, help="Optional suspensions CSV path")
    parser.add_argument("--index-constituents-csv", default=None, help="Optional index constituents CSV path")
    parser.add_argument("--index-code", default="000906")
    parser.add_argument("--index-date", default=None)
    parser.add_argument("--output-dir", default="results/import/csv")
    parser.add_argument("--validate", action="store_true", help="Run CSV contract validation before import")
    parser.add_argument("--start", default=None, help="Expected research start date for validation")
    parser.add_argument("--end", default=None, help="Expected research end date for validation")
    parser.add_argument("--min-symbols", type=int, default=300, help="Minimum symbol count for validation")
    parser.add_argument("--encoding", default="utf-8-sig", help="CSV encoding used by validation/import, e.g. auto")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    metadata = {}
    if args.validate:
        try:
            validation = validate_research_csvs(
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
        write_csv_validation_report(validation, output_dir)
        metadata = {
            "csv_validation_status": validation.status,
            "csv_dataset_fingerprint": validation.dataset_fingerprint,
            "csv_validation_report": str(output_dir / "csv_validation.json"),
        }
        logger.info("CSV validation status: {}", validation.status)
        if validation.status == "BLOCK":
            logger.error("CSV validation blocked import; fix csv_validation.md before retrying.")
            raise SystemExit(2)

    report = import_research_csvs(
        BarStorage(args.cache),
        bars_csv=args.bars_csv,
        stock_info_csv=args.stock_info_csv,
        fundamentals_csv=args.fundamentals_csv,
        calendar_csv=args.calendar_csv,
        suspensions_csv=args.suspensions_csv,
        index_constituents_csv=args.index_constituents_csv,
        index_code=args.index_code,
        index_date=args.index_date,
        encoding=args.encoding,
        metadata=metadata,
    )
    if metadata.get("csv_validation_status") == "WATCH" and report.status == "PASS":
        report = replace(report, status="WATCH")
    out = write_import_report(report, output_dir)
    logger.info("CSV research import status: {}", report.status)
    logger.info("CSV research import report written to {}", out.resolve())
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
