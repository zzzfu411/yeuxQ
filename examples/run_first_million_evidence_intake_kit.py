"""Build the first-million evidence intake kit."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.ops.evidence_intake_kit import build_evidence_intake_kit, write_evidence_intake_kit


def main() -> None:
    parser = argparse.ArgumentParser(description="Build first-million evidence intake kit.")
    parser.add_argument("--report-dir", default="results/first_million")
    parser.add_argument("--data-dir", default="data_exports")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    args = parser.parse_args()

    kit = build_evidence_intake_kit(
        report_dir=args.report_dir,
        data_dir=args.data_dir,
        kit_dir=args.output_dir,
        as_of=args.as_of,
    )
    out = write_evidence_intake_kit(kit, Path(args.output_dir or kit.kit_dir))
    logger.info("First-million evidence intake kit decision: {}", kit.decision)
    logger.info("First-million evidence intake kit written to {}", out.resolve())
    if kit.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
