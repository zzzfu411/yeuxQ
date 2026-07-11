"""Fill a source QA evidence worksheet from explicit operator inputs."""
from __future__ import annotations

import argparse

from loguru import logger

from quantify.data.source_qa_worksheet_fill import fill_source_qa_evidence_worksheet


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fill A-share source QA evidence worksheet rows from explicit evidence notes."
    )
    parser.add_argument("--checklist", default="data_exports/data_source_qa.json")
    parser.add_argument("--worksheet", default="data_exports/data_source_qa_evidence_worksheet.csv")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--vendor", default=None)
    parser.add_argument("--terminal", default=None)
    parser.add_argument("--operator", default=None)
    parser.add_argument("--exported-at", default=None)
    parser.add_argument("--price-adjustment", default=None)
    parser.add_argument("--license-scope", default=None)
    parser.add_argument("--reviewed-by", default=None)
    parser.add_argument("--reviewed-at", default=None)
    parser.add_argument("--source-identity-evidence", default=None)
    parser.add_argument("--license-evidence", default=None)
    parser.add_argument("--price-adjustment-evidence", default=None)
    parser.add_argument("--point-in-time-evidence", default=None)
    parser.add_argument("--manual-signoff-evidence", default=None)
    parser.add_argument("--vendor-evidence", default=None)
    parser.add_argument("--terminal-evidence", default=None)
    parser.add_argument("--operator-evidence", default=None)
    parser.add_argument("--exported-at-evidence", default=None)
    parser.add_argument("--price-adjustment-metadata-evidence", default=None)
    parser.add_argument("--license-scope-evidence", default=None)
    parser.add_argument("--reviewed-by-evidence", default=None)
    parser.add_argument("--reviewed-at-evidence", default=None)
    parser.add_argument("--notes", default=None)
    args = parser.parse_args()

    report, preflight = fill_source_qa_evidence_worksheet(
        checklist_path=args.checklist,
        worksheet_path=args.worksheet,
        output_dir=args.output_dir,
        encoding=args.encoding,
        vendor=args.vendor,
        terminal=args.terminal,
        operator=args.operator,
        exported_at=args.exported_at,
        price_adjustment=args.price_adjustment,
        license_scope=args.license_scope,
        reviewed_by=args.reviewed_by,
        reviewed_at=args.reviewed_at,
        source_identity_evidence=args.source_identity_evidence,
        license_evidence=args.license_evidence,
        price_adjustment_evidence=args.price_adjustment_evidence,
        point_in_time_evidence=args.point_in_time_evidence,
        manual_signoff_evidence=args.manual_signoff_evidence,
        vendor_evidence=args.vendor_evidence,
        terminal_evidence=args.terminal_evidence,
        operator_evidence=args.operator_evidence,
        exported_at_evidence=args.exported_at_evidence,
        price_adjustment_metadata_evidence=args.price_adjustment_metadata_evidence,
        license_scope_evidence=args.license_scope_evidence,
        reviewed_by_evidence=args.reviewed_by_evidence,
        reviewed_at_evidence=args.reviewed_at_evidence,
        notes=args.notes,
    )
    logger.info("Source QA worksheet fill status: {}", report.status)
    logger.info("Source QA worksheet preflight status: {}", preflight.status)
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
