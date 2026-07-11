"""Build the source-QA closeout roll-up."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.source_qa_closeout import build_source_qa_closeout, write_source_qa_closeout


def main() -> None:
    parser = argparse.ArgumentParser(description="Build source-QA closeout roll-up.")
    parser.add_argument("--data-dir", default="data_exports")
    parser.add_argument("--report-dir", default="results/first_million")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--checklist", default=None)
    parser.add_argument("--worksheet", default=None)
    parser.add_argument("--answers", default=None)
    parser.add_argument("--evidence-dir", default=None)
    parser.add_argument("--evidence-manifest", default=None)
    parser.add_argument("--require-evidence-manifest", action="store_true")
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    parser.add_argument("--encoding", default="utf-8-sig")
    args = parser.parse_args()

    closeout = build_source_qa_closeout(
        data_dir=args.data_dir,
        report_dir=args.report_dir,
        checklist_path=args.checklist,
        worksheet_path=args.worksheet,
        answers_path=args.answers,
        evidence_dir=args.evidence_dir,
        evidence_manifest_path=args.evidence_manifest,
        require_evidence_manifest=args.require_evidence_manifest,
        as_of=args.as_of,
        encoding=args.encoding,
    )
    out = write_source_qa_closeout(closeout, Path(args.output_dir or args.report_dir))
    logger.info("Source QA closeout decision: {}", closeout.decision)
    logger.info("Source QA closeout written to {}", out.resolve())
    if closeout.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
