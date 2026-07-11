"""Preflight a filled source QA evidence worksheet before writing answers."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.source_qa import (
    build_data_source_qa_evidence_worksheet_preflight,
    write_data_source_qa_evidence_worksheet_preflight,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Preflight A-share source QA evidence worksheet.")
    parser.add_argument("--checklist", default="data_exports/data_source_qa.json")
    parser.add_argument("--worksheet", default="data_exports/data_source_qa_evidence_worksheet.csv")
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--output-dir", default="data_exports")
    args = parser.parse_args()

    report = build_data_source_qa_evidence_worksheet_preflight(
        checklist_path=args.checklist,
        worksheet_path=args.worksheet,
        encoding=args.encoding,
    )
    out = write_data_source_qa_evidence_worksheet_preflight(report, Path(args.output_dir))
    logger.info("Data source QA worksheet preflight status: {}", report.status)
    logger.info("Data source QA worksheet preflight written to {}", out.resolve())
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
