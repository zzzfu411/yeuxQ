"""Run the read-only external market evidence preflight."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from quantify.data.market_evidence_preflight import (
    build_market_evidence_preflight,
    write_market_evidence_preflight,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Preflight retained CSI 800 total-return and PIT membership evidence without "
            "network or broker access."
        )
    )
    parser.add_argument("--benchmark-csv", required=True, type=Path)
    parser.add_argument("--benchmark-metadata", required=True, type=Path)
    parser.add_argument(
        "--membership-csv",
        "--universe-membership-csv",
        dest="membership_csv",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--membership-metadata",
        "--universe-membership-metadata",
        dest="membership_metadata",
        required=True,
        type=Path,
    )
    parser.add_argument("--required-start-date", "--coverage-start-date", required=True)
    parser.add_argument("--required-end-date", "--coverage-end-date", required=True)
    parser.add_argument("--expected-index-code", default="000906")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--benchmark-date-column", default="date")
    parser.add_argument("--benchmark-value-column", default="value")
    parser.add_argument("--membership-effective-date-column", default="effective_date")
    parser.add_argument("--membership-symbol-column", default="symbol")
    parser.add_argument("--membership-index-code-column", default="index_code")
    parser.add_argument("--minimum-members-per-snapshot", type=int, default=700)
    args = parser.parse_args(argv)

    report = build_market_evidence_preflight(
        args.benchmark_csv,
        args.benchmark_metadata,
        args.membership_csv,
        args.membership_metadata,
        required_start_date=args.required_start_date,
        required_end_date=args.required_end_date,
        expected_index_code=args.expected_index_code,
        benchmark_date_column=args.benchmark_date_column,
        benchmark_value_column=args.benchmark_value_column,
        membership_effective_date_column=args.membership_effective_date_column,
        membership_symbol_column=args.membership_symbol_column,
        membership_index_code_column=args.membership_index_code_column,
        minimum_members_per_snapshot=args.minimum_members_per_snapshot,
    )
    try:
        output = write_market_evidence_preflight(report, args.output_dir)
    except OSError as exc:
        print(f"Market evidence preflight output error: {exc}", file=sys.stderr)
        return 2

    print(f"Market evidence preflight status: {report.status}")
    print(f"Reports written to: {output.resolve()}")
    return 0 if report.status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
