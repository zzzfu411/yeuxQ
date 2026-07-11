"""Write filled source-stage QA answers for offline A-share data exports."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.source_qa import (
    build_data_source_qa_answers,
    build_data_source_qa_answers_from_evidence_worksheet,
    build_data_source_qa_evidence_worksheet_preflight,
    build_data_source_qa_review,
    write_data_source_qa_answers,
    write_data_source_qa_evidence_worksheet_preflight,
    write_data_source_qa_review,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Write source-stage QA answers.")
    parser.add_argument("--checklist", default="data_exports/data_source_qa.json")
    parser.add_argument("--output", default="data_exports/data_source_qa_answers.json")
    parser.add_argument(
        "--worksheet",
        default=None,
        help="Filled data_source_qa_evidence_worksheet.csv/json to convert into answers.",
    )
    parser.add_argument("--vendor", default=None, help="Data vendor or broker name")
    parser.add_argument("--terminal", default=None, help="Terminal or product name")
    parser.add_argument("--operator", default=None, help="Export operator")
    parser.add_argument("--exported-at", default=None, help="Local export timestamp")
    parser.add_argument("--price-adjustment", default="qfq", help="raw/qfq/hfq as exported")
    parser.add_argument("--price-adjustment-evidence", default=None)
    parser.add_argument("--license-scope", default="research and paper trading only")
    parser.add_argument("--license-evidence", default=None)
    parser.add_argument(
        "--point-in-time-evidence",
        default=None,
        help="Vendor PIT evidence, or note that non-PIT fields remain research-only",
    )
    parser.add_argument("--reviewed-by", default=None)
    parser.add_argument("--reviewed-at", default=None)
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--known-limitations", default="")
    parser.add_argument(
        "--evidence-manifest",
        default=None,
        help="Optional source_qa_evidence_manifest.json for strict attachment review.",
    )
    parser.add_argument(
        "--require-evidence-manifest",
        action="store_true",
        help="Require retained local evidence attachments before committing answers.",
    )
    parser.add_argument(
        "--review-output-dir",
        default=None,
        help="Directory for data_source_qa_review.json/md; defaults to the answers output directory.",
    )
    parser.add_argument(
        "--skip-worksheet-preflight",
        action="store_true",
        help="Allow converting a worksheet even if the worksheet preflight would BLOCK.",
    )
    args = parser.parse_args()

    if args.worksheet:
        if not args.skip_worksheet_preflight:
            report = build_data_source_qa_evidence_worksheet_preflight(
                checklist_path=args.checklist,
                worksheet_path=args.worksheet,
                encoding=args.encoding,
            )
            write_data_source_qa_evidence_worksheet_preflight(report, Path(args.output).parent)
            logger.info("Data source QA worksheet preflight status: {}", report.status)
            if report.status == "BLOCK":
                logger.error(
                    "Worksheet preflight BLOCK. Fix data_source_qa_worksheet_preflight.md "
                    "before writing data_source_qa_answers.json."
                )
                raise SystemExit(2)
        answers = build_data_source_qa_answers_from_evidence_worksheet(
            checklist_path=args.checklist,
            worksheet_path=args.worksheet,
            encoding=args.encoding,
        )
    else:
        missing = [
            name
            for name, value in {
                "--vendor": args.vendor,
                "--terminal": args.terminal,
                "--operator": args.operator,
                "--exported-at": args.exported_at,
                "--price-adjustment-evidence": args.price_adjustment_evidence,
                "--license-evidence": args.license_evidence,
                "--point-in-time-evidence": args.point_in_time_evidence,
                "--reviewed-by": args.reviewed_by,
                "--reviewed-at": args.reviewed_at,
            }.items()
            if not str(value or "").strip()
        ]
        if missing:
            raise SystemExit(f"Missing required arguments without --worksheet: {', '.join(missing)}")
        answers = build_data_source_qa_answers(
            checklist_path=args.checklist,
            data_vendor_or_broker=str(args.vendor),
            terminal_or_product_name=str(args.terminal),
            export_operator=str(args.operator),
            exported_at_local_time=str(args.exported_at),
            price_adjustment=args.price_adjustment,
            price_adjustment_evidence=str(args.price_adjustment_evidence),
            license_or_usage_scope=args.license_scope,
            license_evidence=str(args.license_evidence),
            point_in_time_evidence=str(args.point_in_time_evidence),
            reviewed_by=str(args.reviewed_by),
            reviewed_at=str(args.reviewed_at),
            encoding=args.encoding,
            known_limitations=args.known_limitations,
        )
    output_path = Path(args.output)
    if args.require_evidence_manifest:
        out = _write_strict_answers(
            answers,
            output_path=output_path,
            checklist_path=Path(args.checklist),
            evidence_manifest_path=Path(args.evidence_manifest)
            if args.evidence_manifest
            else output_path.parent / "source_qa_evidence_manifest.json",
            review_output_dir=Path(args.review_output_dir) if args.review_output_dir else output_path.parent,
        )
    else:
        out = write_data_source_qa_answers(answers, output_path)
    logger.info("Data source QA answers written to {}", out.resolve())


def _write_strict_answers(
    answers: dict,
    *,
    output_path: Path,
    checklist_path: Path,
    evidence_manifest_path: Path,
    review_output_dir: Path,
) -> Path:
    tmp_path = output_path.with_name(f"{output_path.name}.tmp")
    write_data_source_qa_answers(answers, tmp_path)
    review = build_data_source_qa_review(
        checklist_path=checklist_path,
        answers_path=tmp_path,
        evidence_manifest_path=evidence_manifest_path,
        require_evidence_manifest=True,
    )
    write_data_source_qa_review(review, review_output_dir)
    logger.info("Strict data source QA review status: {}", review.status)
    if review.status == "BLOCK":
        tmp_path.unlink(missing_ok=True)
        logger.error(
            "Strict source QA review BLOCK. Fix data_source_qa_review.md and retained evidence "
            "attachments before writing data_source_qa_answers.json."
        )
        raise SystemExit(2)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.replace(output_path)
    return output_path


if __name__ == "__main__":
    main()
