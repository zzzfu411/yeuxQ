"""Build the source-QA operator packet for real-data evidence collection."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.source_qa_operator_packet import (
    build_source_qa_operator_packet,
    write_source_qa_evidence_dropzone_kit,
    write_source_qa_operator_packet,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build source-QA operator packet.")
    parser.add_argument("--data-dir", default="data_exports")
    parser.add_argument("--report-dir", default="results/first_million")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    parser.add_argument(
        "--write-dropzone-kit",
        action="store_true",
        help="Write README_source_qa_evidence_dropzone.md in the source-QA evidence directory.",
    )
    args = parser.parse_args()

    packet = build_source_qa_operator_packet(
        data_dir=args.data_dir,
        report_dir=args.report_dir,
        as_of=args.as_of,
    )
    out = write_source_qa_operator_packet(packet, Path(args.output_dir or args.report_dir))
    if args.write_dropzone_kit:
        readme = write_source_qa_evidence_dropzone_kit(packet)
        logger.info("Source QA evidence dropzone kit written to {}", readme.resolve())
    logger.info("Source QA operator packet decision: {}", packet.decision)
    logger.info("Source QA operator packet written to {}", out.resolve())
    if packet.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
