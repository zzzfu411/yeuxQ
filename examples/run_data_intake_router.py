"""Select the best guarded route for acquiring recent A-share data."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.intake_router import build_data_intake_router, write_data_intake_router


def main() -> None:
    parser = argparse.ArgumentParser(description="Route recent A-share data intake.")
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
        help="Require source QA evidence attachments before recommending broker/vendor CSV intake",
    )
    parser.add_argument(
        "--latest-import-report",
        default="results/import/recent/data_import.json",
        help="Optional provider import attempt report",
    )
    parser.add_argument(
        "--tdx-search-dir",
        action="append",
        default=None,
        help="Optional TDX vipdoc or lday directory; can be supplied multiple times",
    )
    parser.add_argument("--output-dir", default="results/first_million")
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    parser.add_argument("--encoding", default="utf-8-sig")
    args = parser.parse_args()

    report = build_data_intake_router(
        data_dir=args.data_dir,
        config_path=args.config,
        source_qa_answers=args.source_qa_answers,
        source_qa_evidence_manifest=args.source_qa_evidence_manifest,
        require_source_qa_evidence_manifest=args.require_source_qa_evidence_manifest,
        latest_import_report_path=args.latest_import_report,
        tdx_search_dirs=args.tdx_search_dir,
        min_symbols=args.min_symbols,
        as_of=args.as_of,
        encoding=args.encoding,
    )
    out = write_data_intake_router(report, Path(args.output_dir))
    logger.info("Data intake router status: {}", report.status)
    logger.info("Recommended data route: {}", report.recommended_route)
    logger.info("Data intake router written to {}", out.resolve())
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
