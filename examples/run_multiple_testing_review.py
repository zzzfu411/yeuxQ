"""Build a fail-closed multiple-testing review from frozen trial returns."""

from __future__ import annotations

import argparse
from pathlib import Path

from quantify.research.multiple_testing import (
    build_multiple_testing_report,
    write_multiple_testing_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Review frozen trial returns with Deflated Sharpe and CSCV/PBO."
    )
    parser.add_argument("--input-csv", required=True, help="CSV with date then daily trial returns")
    parser.add_argument(
        "--output-dir", required=True, help="Directory for JSON and Markdown reports"
    )
    parser.add_argument("--selected-candidate", required=True, help="Frozen selected trial column")
    parser.add_argument("--periods-per-year", required=True, type=float)
    parser.add_argument("--partition-count", required=True, type=int)
    parser.add_argument("--max-combinations", type=int, default=None)
    parser.add_argument(
        "--effective-trials",
        type=float,
        default=None,
        help="Optional conservative override; cannot be below the CSV trial count",
    )
    args = parser.parse_args()

    report = build_multiple_testing_report(
        args.input_csv,
        selected_candidate=args.selected_candidate,
        periods_per_year=args.periods_per_year,
        partition_count=args.partition_count,
        max_combinations=args.max_combinations,
        effective_trials=args.effective_trials,
    )
    output = write_multiple_testing_report(report, Path(args.output_dir))
    print(f"Multiple-testing status: {report.status}")
    print(f"Reports written to: {output.resolve()}")


if __name__ == "__main__":
    main()
