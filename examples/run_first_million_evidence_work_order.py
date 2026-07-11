"""Build the first-million evidence work order."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.ops.evidence_work_order import build_evidence_work_order, write_evidence_work_order


def main() -> None:
    parser = argparse.ArgumentParser(description="Build first-million evidence work order.")
    parser.add_argument("--report-dir", default="results/first_million")
    parser.add_argument("--data-dir", default="data_exports")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    args = parser.parse_args()

    order = build_evidence_work_order(
        report_dir=args.report_dir,
        data_dir=args.data_dir,
        as_of=args.as_of,
    )
    out = write_evidence_work_order(order, Path(args.output_dir or args.report_dir))
    logger.info("First-million evidence work order decision: {}", order.decision)
    logger.info("First-million evidence work order written to {}", out.resolve())
    if order.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
