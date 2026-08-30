"""Fetch one post-close frozen-universe date into sealed quarantine."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from quantify.data.prospective_daily_acquisition import (
    build_prospective_daily_acquisition_preflight,
    handoff_prospective_daily_acquisition,
    run_prospective_daily_acquisition,
    write_prospective_daily_acquisition,
)
from quantify.data.prospective_acquisition_journal import (
    record_prospective_acquisition_attempt,
)
from quantify.research.sealed_holdout_intake import SealedHoldoutIntakeError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "After the A-share close, fetch one frozen-universe date through AKShare into "
            "sealed quarantine without writing the execution cache or running a strategy."
        )
    )
    parser.add_argument("--packet-dir", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--market-date", default=None)
    parser.add_argument("--calendar-csv", type=Path)
    parser.add_argument("--calendar-metadata", type=Path)
    parser.add_argument("--minimum-success-ratio", type=float, default=0.95)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--retry-delay-seconds", type=float, default=1.0)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)

    report = build_prospective_daily_acquisition_preflight(
        packet_dir=args.packet_dir,
        trial_registry_path=args.registry,
        output_dir=args.output_dir,
        market_date=args.market_date,
        minimum_success_ratio=args.minimum_success_ratio,
        calendar_csv=args.calendar_csv,
        calendar_metadata=args.calendar_metadata,
    )
    if report.status == "MARKET_CLOSED":
        _print_summary(report, args.output_dir, report_written=False)
        return 0
    write_prospective_daily_acquisition(report, args.output_dir)
    if args.preflight_only:
        _print_summary(report, args.output_dir)
        return 0 if report.status in {"READY", "ALREADY_RETAINED", "MARKET_CLOSED"} else 2
    if report.status in {"BLOCK", "ALREADY_RETAINED", "MARKET_CLOSED"}:
        _print_summary(report, args.output_dir)
        return 0 if report.status in {"ALREADY_RETAINED", "MARKET_CLOSED"} else 2

    try:
        report = run_prospective_daily_acquisition(
            report,
            output_dir=args.output_dir,
            max_attempts=args.max_attempts,
            retry_delay_seconds=args.retry_delay_seconds,
        )
        attempt_event = record_prospective_acquisition_attempt(report, args.output_dir)
        print(
            "Acquisition attempt journaled: "
            f"sequence={attempt_event['sequence']} hash={attempt_event['event_hash']}"
        )
        write_prospective_daily_acquisition(report, args.output_dir)
        if report.status == "PASS":
            intake = handoff_prospective_daily_acquisition(
                report,
                packet_dir=args.packet_dir,
                trial_registry_path=args.registry,
                output_dir=args.output_dir,
            )
            print(f"Quarantine retained: {intake.retained}")
    except (OSError, RuntimeError, SealedHoldoutIntakeError, ValueError) as exc:
        print(f"Prospective daily acquisition failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    _print_summary(report, args.output_dir)
    return 0 if report.status == "PASS" else 2


def _print_summary(report, output_dir: Path, *, report_written: bool = True) -> None:
    print(f"Prospective daily acquisition status: {report.status}")
    print(f"Market date: {report.market_date}")
    print(f"Calendar evidence: {report.calendar_evidence_status}")
    print(f"Calendar session: {report.calendar_session_status}")
    print(f"Fetch allowed: {report.fetch_allowed}")
    print(f"Success ratio: {report.success_ratio:.2%}")
    print("Execution-cache write allowed: False")
    print("Holdout analysis allowed: False")
    if report_written:
        print(f"Report: {(output_dir / 'prospective_daily_acquisition.json').resolve()}")
    else:
        print("Report: not written (reviewed market-closure no-op)")


if __name__ == "__main__":
    raise SystemExit(main())
