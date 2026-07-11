"""Review filled source-level QA answers before offline A-share data intake."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.source_qa import build_data_source_qa_review, write_data_source_qa_review


def main() -> None:
    parser = argparse.ArgumentParser(description="Review A-share data source QA answers.")
    parser.add_argument("--checklist", default="data_exports/data_source_qa.json")
    parser.add_argument("--answers", default="data_exports/data_source_qa_answers.json")
    parser.add_argument("--review-stage", choices=["source", "csv_validation"], default="source")
    parser.add_argument("--validation-report", default=None)
    parser.add_argument("--evidence-manifest", default=None)
    parser.add_argument("--require-evidence-manifest", action="store_true")
    parser.add_argument("--output-dir", default="results/import/source_qa")
    args = parser.parse_args()

    review = build_data_source_qa_review(
        checklist_path=args.checklist,
        answers_path=args.answers,
        review_stage=args.review_stage,
        validation_report_path=args.validation_report,
        evidence_manifest_path=args.evidence_manifest,
        require_evidence_manifest=args.require_evidence_manifest,
    )
    out = write_data_source_qa_review(review, Path(args.output_dir))
    logger.info("Data source QA review status: {}", review.status)
    logger.info("Data source QA review written to {}", out.resolve())
    if review.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
