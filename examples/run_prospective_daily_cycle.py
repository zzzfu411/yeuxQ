"""Run one explicit, sealed prospective daily collection cycle."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from quantify.ops.prospective_daily_cycle import (
    run_prospective_daily_cycle,
    write_prospective_daily_cycle,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the earliest prospective collection gap offline by default; "
            "provider acquisition requires explicit execution and retry authorization."
        )
    )
    parser.add_argument("--packet-dir", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--quarantine-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--calendar-csv", type=Path)
    parser.add_argument("--calendar-metadata", type=Path)
    parser.add_argument("--execute-acquisition", action="store_true")
    parser.add_argument("--retry-blocked-attempt", action="store_true")
    parser.add_argument("--minimum-success-ratio", type=float, default=0.95)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--retry-delay-seconds", type=float, default=1.0)
    args = parser.parse_args(argv)

    try:
        report = run_prospective_daily_cycle(
            packet_dir=args.packet_dir,
            trial_registry_path=args.registry,
            quarantine_root=args.quarantine_root,
            cycle_output_dir=args.output_dir,
            calendar_csv=args.calendar_csv,
            calendar_metadata=args.calendar_metadata,
            execute_acquisition=args.execute_acquisition,
            retry_blocked_attempt=args.retry_blocked_attempt,
            minimum_success_ratio=args.minimum_success_ratio,
            max_attempts=args.max_attempts,
            retry_delay_seconds=args.retry_delay_seconds,
        )
        output = write_prospective_daily_cycle(report, args.output_dir)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Prospective daily cycle failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"Prospective daily cycle: {report.status}")
    print(f"Target date: {report.target_date or 'none'}")
    print(f"Execution requested: {report.execution_requested}")
    print(f"Execution performed: {report.execution_performed}")
    print(f"Network access: {report.network_access}")
    print("Holdout analysis allowed: False")
    print("Broker access: False")
    print(f"Report: {(output / 'prospective_daily_cycle.json').resolve()}")
    return 2 if report.status in {"BLOCK", "REVIEW_REQUIRED"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
