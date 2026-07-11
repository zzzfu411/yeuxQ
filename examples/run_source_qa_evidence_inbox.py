"""Scan local source-QA evidence files and map them to required attachment ids."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.source_qa_evidence_inbox import (
    build_source_qa_evidence_inbox,
    write_source_qa_evidence_inbox,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the source-QA evidence inbox report.")
    parser.add_argument("--data-dir", default="data_exports")
    parser.add_argument("--report-dir", default="results/first_million")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--checklist", default=None)
    parser.add_argument("--evidence-dir", default=None)
    parser.add_argument("--evidence-manifest", default=None)
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    parser.add_argument("--max-suggestions-per-item", type=int, default=3)
    args = parser.parse_args()

    report = build_source_qa_evidence_inbox(
        data_dir=args.data_dir,
        report_dir=args.report_dir,
        checklist_path=args.checklist,
        evidence_dir=args.evidence_dir,
        manifest_path=args.evidence_manifest,
        as_of=args.as_of,
        max_suggestions_per_item=args.max_suggestions_per_item,
    )
    out = write_source_qa_evidence_inbox(report, Path(args.output_dir or args.report_dir))
    logger.info("Source QA evidence inbox status: {}", report.status)
    logger.info("Source QA evidence inbox written to {}", out.resolve())
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
