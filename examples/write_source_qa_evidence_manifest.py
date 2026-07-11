"""Write a local source-QA evidence attachment manifest."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.source_qa import (
    build_source_qa_evidence_manifest,
    build_source_qa_evidence_manifest_preflight,
    write_source_qa_evidence_manifest,
    write_source_qa_evidence_manifest_preflight,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Write source-QA evidence attachment manifest.")
    parser.add_argument("--checklist", default="data_exports/data_source_qa.json")
    parser.add_argument("--evidence-dir", default="data_exports/source_qa_evidence")
    parser.add_argument("--output-dir", default="data_exports")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 when manifest preflight is BLOCK.",
    )
    args = parser.parse_args()

    manifest = build_source_qa_evidence_manifest(
        checklist_path=args.checklist,
        evidence_dir=args.evidence_dir,
    )
    out = write_source_qa_evidence_manifest(manifest, Path(args.output_dir))
    preflight = build_source_qa_evidence_manifest_preflight(
        checklist_path=args.checklist,
        manifest_path=Path(args.output_dir) / "source_qa_evidence_manifest.json",
        evidence_dir=args.evidence_dir,
    )
    write_source_qa_evidence_manifest_preflight(preflight, Path(args.output_dir))
    logger.info("Source QA evidence manifest items: {}", len(manifest.items))
    logger.info("Source QA evidence manifest written to {}", out.resolve())
    logger.info("Source QA evidence manifest preflight status: {}", preflight.status)
    if args.strict and preflight.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
