"""Write offline CSV templates for broker/vendor A-share research exports."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.csv_contract import write_research_csv_templates


def main() -> None:
    parser = argparse.ArgumentParser(description="Write offline research CSV templates.")
    parser.add_argument("--output-dir", default="data_exports", help="Directory to write templates")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing template files")
    args = parser.parse_args()

    try:
        paths = write_research_csv_templates(Path(args.output_dir), overwrite=args.overwrite)
    except FileExistsError as exc:
        logger.error("{}", exc)
        raise SystemExit(2) from exc
    logger.info("Wrote {} offline CSV template files to {}", len(paths), Path(args.output_dir).resolve())


if __name__ == "__main__":
    main()
