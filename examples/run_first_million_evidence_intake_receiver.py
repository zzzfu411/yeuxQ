"""Review or receive staged first-million evidence intake files."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.ops.evidence_intake_receiver import (
    receive_evidence_intake,
    write_evidence_intake_receipt,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Review or copy staged first-million evidence files.")
    parser.add_argument(
        "--manifest",
        default="results/first_million/evidence_intake_kit/first_million_evidence_intake_manifest.csv",
    )
    parser.add_argument("--kit-dir", default=None)
    parser.add_argument("--data-dir", default="data_exports")
    parser.add_argument("--report-dir", default="results/first_million")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    parser.add_argument("--config", default="config/research_recent.yaml")
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--apply", action="store_true", help="Copy accepted staged files to target paths.")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing existing target files.")
    args = parser.parse_args()

    receipt = receive_evidence_intake(
        manifest_path=args.manifest,
        kit_dir=args.kit_dir,
        data_dir=args.data_dir,
        report_dir=args.report_dir,
        as_of=args.as_of,
        apply=args.apply,
        overwrite=args.overwrite,
        encoding=args.encoding,
        config_path=args.config,
        min_symbols=args.min_symbols,
    )
    out = write_evidence_intake_receipt(
        receipt,
        Path(args.output_dir or args.kit_dir or Path(args.manifest).parent),
    )
    logger.info("First-million evidence intake receipt decision: {}", receipt.decision)
    logger.info("First-million evidence intake receipt written to {}", out.resolve())
    if receipt.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
