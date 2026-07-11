"""Diagnose offline CSV exports before importing recent A-share research data."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.import_doctor import build_data_import_doctor, write_data_import_doctor_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose offline CSV research exports.")
    parser.add_argument("--data-dir", default="data_exports", help="Directory containing CSV exports")
    parser.add_argument("--config", default=None, help="Optional research config for dates and cache path")
    parser.add_argument("--cache", default=None, help="Override SQLite cache path in generated commands")
    parser.add_argument("--start", default=None, help="Expected research start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="Expected research end date YYYY-MM-DD")
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument("--encoding", default="utf-8-sig", help="CSV encoding, e.g. utf-8-sig or gbk")
    parser.add_argument(
        "--latest-import-report",
        default=None,
        help="Optional provider import attempt JSON, used to explain network/proxy failure context",
    )
    parser.add_argument("--output-dir", default="results/import/doctor")
    args = parser.parse_args()

    try:
        report = build_data_import_doctor(
            data_dir=args.data_dir,
            config_path=args.config,
            cache_path=args.cache,
            start=args.start,
            end=args.end,
            min_symbols=args.min_symbols,
            encoding=args.encoding,
            latest_import_report_path=args.latest_import_report,
        )
    except ValueError as exc:
        logger.error("{}", exc)
        raise SystemExit(2) from exc
    out = write_data_import_doctor_report(report, Path(args.output_dir))
    logger.info("Data import doctor status: {}", report.status)
    logger.info("Data import doctor report written to {}", out.resolve())
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
