"""Write a source-level QA checklist for offline A-share research exports."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.source_qa import build_data_source_qa, write_data_source_qa


def main() -> None:
    parser = argparse.ArgumentParser(description="Write an A-share data source QA checklist.")
    parser.add_argument("--config", default="config/research_recent.yaml", help="Research config path")
    parser.add_argument("--output-dir", default="data_exports", help="Directory to write QA files")
    parser.add_argument("--start", default=None, help="Override research start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="Override research end date YYYY-MM-DD")
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument("--as-of", default=None, help="Optional QA as-of date YYYY-MM-DD")
    args = parser.parse_args()

    checklist = build_data_source_qa(
        config_path=args.config,
        output_dir=args.output_dir,
        start=args.start,
        end=args.end,
        min_symbols=args.min_symbols,
        as_of=args.as_of,
    )
    out = write_data_source_qa(checklist, Path(args.output_dir))
    logger.info("Data source QA checklist written to {}", out.resolve())


if __name__ == "__main__":
    main()
