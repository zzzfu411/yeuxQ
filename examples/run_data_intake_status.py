"""Build the combined first-million data/source-QA intake status report."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.ops.data_intake_status import build_data_intake_status, write_data_intake_status


def main() -> None:
    parser = argparse.ArgumentParser(description="Build combined first-million data intake status.")
    parser.add_argument("--report-dir", default="results/first_million")
    parser.add_argument("--data-dir", default="data_exports")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    args = parser.parse_args()

    report = build_data_intake_status(
        report_dir=args.report_dir,
        data_dir=args.data_dir,
        as_of=args.as_of,
    )
    out = write_data_intake_status(report, Path(args.output_dir or args.report_dir))
    logger.info("Data intake status decision: {}", report.decision)
    logger.info("Data intake status written to {}", out.resolve())
    if report.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
