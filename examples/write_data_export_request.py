"""Write a vendor-facing data export request for offline A-share research CSVs."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.export_request import build_data_export_request, write_data_export_request


def main() -> None:
    parser = argparse.ArgumentParser(description="Write an offline A-share data export request.")
    parser.add_argument("--config", default="config/research_recent.yaml", help="Research config path")
    parser.add_argument("--output-dir", default="data_exports", help="Directory to write request files")
    parser.add_argument("--start", default=None, help="Override research start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="Override research end date YYYY-MM-DD")
    parser.add_argument("--min-symbols", type=int, default=300)
    args = parser.parse_args()

    request = build_data_export_request(
        config_path=args.config,
        output_dir=args.output_dir,
        start=args.start,
        end=args.end,
        min_symbols=args.min_symbols,
    )
    out = write_data_export_request(request, Path(args.output_dir))
    logger.info("Data export request written to {}", out.resolve())


if __name__ == "__main__":
    main()
