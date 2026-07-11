"""Build a readiness report for an offline A-share data package."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.offline_package import (
    build_offline_data_package_report,
    write_offline_data_package_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build offline data package readiness report.")
    parser.add_argument("--data-dir", default="data_exports", help="Offline CSV export directory")
    parser.add_argument("--config", default="config/research_recent.yaml", help="Recent A-share config")
    parser.add_argument("--source-qa-answers", default=None, help="Filled data_source_qa_answers.json")
    parser.add_argument(
        "--source-qa-evidence-manifest",
        default=None,
        help="Optional source_qa_evidence_manifest.json path",
    )
    parser.add_argument(
        "--require-source-qa-evidence-manifest",
        action="store_true",
        help="Require source QA evidence attachments to pass strict review",
    )
    parser.add_argument("--output-dir", default="results/first_million")
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    parser.add_argument("--encoding", default="utf-8-sig")
    args = parser.parse_args()

    report = build_offline_data_package_report(
        data_dir=args.data_dir,
        config_path=args.config,
        source_qa_answers=args.source_qa_answers,
        source_qa_evidence_manifest=args.source_qa_evidence_manifest,
        require_source_qa_evidence_manifest=args.require_source_qa_evidence_manifest,
        min_symbols=args.min_symbols,
        as_of=args.as_of,
        encoding=args.encoding,
    )
    out = write_offline_data_package_report(report, Path(args.output_dir))
    logger.info("Offline data package status: {}", report.status)
    logger.info("Offline data package report written to {}", out.resolve())
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
