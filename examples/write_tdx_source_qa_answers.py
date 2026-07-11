"""Write source-stage QA answers for local TongDaXin .day OHLCV exports."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.tdx_source_qa import (
    build_tdx_source_qa_answers,
    write_tdx_source_qa_answers,
    write_tdx_source_qa_support_artifacts,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Write TDX-specific source-stage QA answers.")
    parser.add_argument("--checklist", default="data_exports/data_source_qa.json")
    parser.add_argument("--output", default="data_exports/data_source_qa_answers.json")
    parser.add_argument("--tdx-export-report", default="data_exports/tdx_day_export.json")
    parser.add_argument("--input-dir", default=None, help="Original TDX vipdoc or lday directory")
    parser.add_argument("--vendor", default="TongDaXin local .day files")
    parser.add_argument("--terminal", default="TongDaXin")
    parser.add_argument("--operator", required=True, help="Human operator who prepared the export")
    parser.add_argument("--exported-at", required=True, help="Local export/conversion timestamp")
    parser.add_argument("--price-adjustment", default=None, help="raw/qfq/hfq as evidenced by TDX")
    parser.add_argument(
        "--price-adjustment-evidence",
        required=True,
        help="Real TDX setting, screenshot note, or operator evidence for raw/qfq/hfq",
    )
    parser.add_argument("--license-scope", default="research and paper trading only")
    parser.add_argument("--license-evidence", required=True)
    parser.add_argument(
        "--pit-fundamental-evidence",
        default=None,
        help="Separate PIT fundamental/index evidence, if available; otherwise OHLCV-only is recorded",
    )
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--reviewed-at", required=True)
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--known-limitations", default="")
    parser.add_argument("--worksheet", default="data_exports/data_source_qa_evidence_worksheet.csv")
    parser.add_argument("--evidence-dir", default="data_exports/source_qa_evidence")
    parser.add_argument("--manifest-output", default="data_exports/source_qa_evidence_manifest.json")
    parser.add_argument(
        "--write-support-artifacts",
        action="store_true",
        help="Also write worksheet, note-style evidence files, and source_qa_evidence_manifest.json from the supplied TDX evidence fields.",
    )
    args = parser.parse_args()

    answers = build_tdx_source_qa_answers(
        checklist_path=args.checklist,
        tdx_export_report=args.tdx_export_report,
        input_dir=args.input_dir,
        data_vendor_or_broker=args.vendor,
        terminal_or_product_name=args.terminal,
        export_operator=args.operator,
        exported_at_local_time=args.exported_at,
        price_adjustment=args.price_adjustment,
        price_adjustment_evidence=args.price_adjustment_evidence,
        license_or_usage_scope=args.license_scope,
        license_evidence=args.license_evidence,
        pit_fundamental_evidence=args.pit_fundamental_evidence,
        reviewed_by=args.reviewed_by,
        reviewed_at=args.reviewed_at,
        encoding=args.encoding,
        known_limitations=args.known_limitations,
    )
    out = write_tdx_source_qa_answers(answers, Path(args.output))
    if args.write_support_artifacts:
        write_tdx_source_qa_support_artifacts(
            answers,
            checklist_path=args.checklist,
            worksheet_path=args.worksheet,
            evidence_dir=args.evidence_dir,
            manifest_path=args.manifest_output,
            encoding=args.encoding,
        )
    logger.info("TDX source QA answers written to {}", out.resolve())


if __name__ == "__main__":
    main()
