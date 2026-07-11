"""Preview offline CSV files before guarded research import."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.csv_intake_preview import build_csv_intake_preview, write_csv_intake_preview


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview offline research CSV files.")
    parser.add_argument("--data-dir", default="data_exports", help="Offline CSV export directory")
    parser.add_argument("--encoding", default="utf-8-sig", help="CSV encoding, e.g. auto, utf-8-sig, or gbk")
    parser.add_argument("--sample-rows", type=int, default=3)
    parser.add_argument("--output-dir", default="results/import/csv_preview")
    args = parser.parse_args()

    preview = build_csv_intake_preview(
        data_dir=args.data_dir,
        encoding=args.encoding,
        sample_rows=args.sample_rows,
    )
    out = write_csv_intake_preview(preview, Path(args.output_dir))
    logger.info("CSV intake preview status: {}", preview.status)
    logger.info("CSV intake preview written to {}", out.resolve())
    if preview.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
