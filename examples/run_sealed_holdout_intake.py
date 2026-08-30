"""Retain one finalized daily-bars CSV in prospective quarantine."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from quantify.research.sealed_holdout_intake import (
    SealedHoldoutIntakeError,
    build_sealed_holdout_intake,
    retain_sealed_holdout_intake,
    write_sealed_holdout_intake_report,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and retain exact daily CSV bytes in a sealed, unreviewed quarantine. "
            "This command never writes the execution cache or runs a strategy."
        )
    )
    parser.add_argument("--packet-dir", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--daily-bars-csv", required=True, type=Path)
    parser.add_argument("--source-vendor", required=True)
    parser.add_argument("--source-reference", required=True)
    parser.add_argument("--source-exported-at", required=True)
    parser.add_argument("--price-adjustment", required=True, choices=("raw", "qfq", "hfq"))
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    report = build_sealed_holdout_intake(
        packet_dir=args.packet_dir,
        trial_registry_path=args.registry,
        daily_bars_csv=args.daily_bars_csv,
        output_dir=args.output_dir,
        source_vendor=args.source_vendor,
        source_reference=args.source_reference,
        source_exported_at=args.source_exported_at,
        price_adjustment=args.price_adjustment,
    )
    if report.status == "BLOCK":
        write_sealed_holdout_intake_report(report, args.output_dir)
    else:
        try:
            report = retain_sealed_holdout_intake(
                report,
                daily_bars_csv=args.daily_bars_csv,
                output_dir=args.output_dir,
            )
        except (OSError, SealedHoldoutIntakeError) as exc:
            print(f"Sealed holdout intake commit failed: {exc}", file=sys.stderr)
            return 2

    print(f"Sealed holdout intake status: {report.status}")
    print(f"Market date: {report.market_date or 'unavailable'}")
    print(f"Retained: {report.retained}")
    print(f"Idempotent: {report.idempotent}")
    print("Execution-cache write allowed: False")
    print("Holdout analysis allowed: False")
    print(f"Report: {(args.output_dir / 'sealed_holdout_intake.json').resolve()}")
    return 0 if report.retained else 2


if __name__ == "__main__":
    raise SystemExit(main())
