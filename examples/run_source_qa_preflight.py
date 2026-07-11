"""Preflight source QA answers before guarded offline intake."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.source_qa_preflight import build_source_qa_preflight, write_source_qa_preflight


def main() -> None:
    parser = argparse.ArgumentParser(description="Preflight A-share source QA answers.")
    parser.add_argument("--checklist", default="data_exports/data_source_qa.json")
    parser.add_argument("--answers", default="data_exports/data_source_qa_answers.json")
    parser.add_argument("--evidence-manifest", default=None)
    parser.add_argument("--require-evidence-manifest", action="store_true")
    parser.add_argument("--output-dir", default="results/import/source_qa")
    args = parser.parse_args()

    report = build_source_qa_preflight(
        checklist_path=args.checklist,
        answers_path=args.answers,
        evidence_manifest_path=args.evidence_manifest,
        require_evidence_manifest=args.require_evidence_manifest,
        output_dir=args.output_dir,
    )
    out = write_source_qa_preflight(report, Path(args.output_dir))
    logger.info("Source QA preflight status: {}", report.status)
    logger.info("Source QA preflight written to {}", out.resolve())
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
