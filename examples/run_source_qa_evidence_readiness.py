"""Run unified source-QA evidence readiness checks."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.source_qa_readiness import (
    build_source_qa_evidence_readiness,
    write_source_qa_evidence_readiness,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run unified source-QA evidence readiness.")
    parser.add_argument("--checklist", default="data_exports/data_source_qa.json")
    parser.add_argument("--worksheet", default="data_exports/data_source_qa_evidence_worksheet.csv")
    parser.add_argument("--answers", default="data_exports/data_source_qa_answers.json")
    parser.add_argument("--evidence-manifest", default="data_exports/source_qa_evidence_manifest.json")
    parser.add_argument("--evidence-dir", default=None)
    parser.add_argument("--require-evidence-manifest", action="store_true")
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--output-dir", default="results/import/source_qa")
    args = parser.parse_args()

    report = build_source_qa_evidence_readiness(
        checklist_path=args.checklist,
        worksheet_path=args.worksheet,
        answers_path=args.answers,
        evidence_manifest_path=args.evidence_manifest,
        review_artifact_path=Path(args.output_dir) / "data_source_qa_review.json",
        evidence_dir=args.evidence_dir,
        require_evidence_manifest=args.require_evidence_manifest,
        encoding=args.encoding,
    )
    out = write_source_qa_evidence_readiness(report, Path(args.output_dir))
    logger.info("Source QA evidence readiness status: {}", report.status)
    logger.info("Source QA evidence readiness written to {}", out.resolve())
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
