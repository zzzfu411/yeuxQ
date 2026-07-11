"""Convert TongDaXin .day files into offline research CSV files."""
from __future__ import annotations

import argparse

from loguru import logger

from quantify.data.tdx_day import export_tdx_day_to_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert TongDaXin .day files to bars.csv.")
    parser.add_argument(
        "--input-dir",
        required=True,
        help="TongDaXin vipdoc directory, lday directory, or a single .day file",
    )
    parser.add_argument("--output-dir", default="data_exports", help="Output CSV directory")
    parser.add_argument("--start", default=None, help="Optional start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="Optional end date YYYY-MM-DD")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols to include")
    parser.add_argument("--include-indices", action="store_true", help="Include non-stock index-style .day files")
    parser.add_argument("--no-stock-info", action="store_true", help="Do not write stock_info.csv")
    parser.add_argument("--no-calendar", action="store_true", help="Do not write calendar.csv")
    args = parser.parse_args()

    report = export_tdx_day_to_csv(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        start=args.start,
        end=args.end,
        symbols=[item.strip() for item in args.symbols.split(",") if item.strip()] or None,
        include_indices=args.include_indices,
        write_stock_info=not args.no_stock_info,
        write_calendar=not args.no_calendar,
    )
    logger.info("TongDaXin day export status: {}", report.status)
    logger.info("TongDaXin day export written to {}", args.output_dir)
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
