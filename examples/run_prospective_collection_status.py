"""Report prospective quarantine continuity without network or analysis."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from quantify.research.prospective_collection_status import (
    build_prospective_collection_status,
    write_prospective_collection_status,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify frozen packet/registry/quarantine continuity and report the earliest "
            "unresolved candidate weekday without provider or broker access."
        )
    )
    parser.add_argument("--packet-dir", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--quarantine-root", required=True, type=Path)
    parser.add_argument("--calendar-csv", type=Path)
    parser.add_argument("--calendar-metadata", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    report = build_prospective_collection_status(
        packet_dir=args.packet_dir,
        trial_registry_path=args.registry,
        quarantine_root=args.quarantine_root,
        calendar_csv=args.calendar_csv,
        calendar_metadata=args.calendar_metadata,
    )
    output = write_prospective_collection_status(report, args.output_dir)
    print(f"Prospective collection status: {report.status}")
    print(f"Finalized through: {report.finalized_through}")
    print(f"Retained dates: {len(report.retained_dates)}")
    print(f"Provider attempt journal: {report.attempt_journal_status}")
    print(f"Provider attempt events: {report.attempt_event_count}")
    continuity_label = (
        "reviewed open sessions"
        if report.calendar_evidence_status == "PASS"
        else "candidate weekdays"
    )
    print(f"Unresolved {continuity_label}: {len(report.unresolved_dates)}")
    print(f"Earliest unresolved: {report.earliest_unresolved_date or 'none'}")
    print("Network access: False")
    print("Holdout analysis allowed: False")
    print(f"Report: {(output / 'prospective_collection_status.json').resolve()}")
    return 2 if report.status == "BLOCK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
