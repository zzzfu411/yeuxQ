"""Normalize raw broker/vendor daily bars into data_exports/bars.csv."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.vendor_bars_normalizer import (
    normalize_vendor_bars,
    write_vendor_bars_normalization_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize raw broker/vendor A-share daily bars into the offline bars.csv "
            "contract. Supports common English and Chinese OHLCV headers."
        )
    )
    parser.add_argument("--input", required=True, help="Raw broker/vendor daily bars CSV path")
    parser.add_argument("--output-dir", default="data_exports", help="Directory that will receive bars.csv")
    parser.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="CSV encoding; use auto for GBK/GB18030 Chinese broker exports.",
    )
    parser.add_argument("--start", default=None, help="Optional start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="Optional end date YYYY-MM-DD")
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument(
        "--report-dir",
        default=None,
        help="Report directory; defaults to --output-dir.",
    )
    args = parser.parse_args()

    report = normalize_vendor_bars(
        input_path=args.input,
        output_dir=args.output_dir,
        encoding=args.encoding,
        start=args.start,
        end=args.end,
        min_symbols=args.min_symbols,
    )
    report_dir = Path(args.report_dir or args.output_dir)
    out = write_vendor_bars_normalization_report(report, report_dir)
    logger.info("Vendor bars normalization status: {}", report.status)
    logger.info("Vendor bars normalization report written to {}", out.resolve())
    if report.output_bars_csv:
        logger.info("Normalized bars written to {}", Path(report.output_bars_csv).resolve())
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
