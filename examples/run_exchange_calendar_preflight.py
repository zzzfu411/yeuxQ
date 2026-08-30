"""Validate reviewed A-share exchange-calendar evidence locally."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from quantify.data.exchange_calendar_preflight import (
    build_exchange_calendar_preflight,
    write_exchange_calendar_preflight,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a reviewed, hash-bound, complete natural-day A-share exchange calendar "
            "without network or broker access."
        )
    )
    parser.add_argument("--calendar-csv", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--required-start-date", required=True)
    parser.add_argument("--required-end-date", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    report = build_exchange_calendar_preflight(
        args.calendar_csv,
        args.metadata,
        required_start_date=args.required_start_date,
        required_end_date=args.required_end_date,
    )
    try:
        output = write_exchange_calendar_preflight(report, args.output_dir)
    except OSError as exc:
        print(f"Exchange calendar preflight output failed: {exc}", file=sys.stderr)
        return 2
    print(f"Exchange calendar preflight status: {report.status}")
    print(f"Open sessions: {report.open_session_count}")
    print(f"Calendar days: {report.calendar_day_count}")
    print("Network access: False")
    print("Broker access: False")
    print(f"Report: {(output / 'exchange_calendar_preflight.json').resolve()}")
    return 0 if report.status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
