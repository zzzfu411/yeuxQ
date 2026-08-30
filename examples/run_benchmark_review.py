"""Build a formal, fail-closed benchmark review from CSV inputs."""
from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from quantify.research.benchmark_report import (
    BenchmarkReviewInputError,
    build_benchmark_review_report,
    write_benchmark_review_report,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Review strategy equity against an attested total-return benchmark."
    )
    parser.add_argument("--strategy-equity-csv", required=True, type=Path)
    parser.add_argument("--benchmark-csv", required=True, type=Path)
    parser.add_argument("--benchmark-metadata", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--strategy-date-column", default="timestamp")
    parser.add_argument("--strategy-value-column", default="equity")
    parser.add_argument("--benchmark-date-column", default="date")
    parser.add_argument("--benchmark-value-column", default="value")
    parser.add_argument("--periods-per-year", type=int, default=252)
    parser.add_argument("--block-size", type=int, default=5)
    parser.add_argument("--n-bootstrap", type=int, default=1_000)
    parser.add_argument("--random-seed", type=int, default=0)
    args = parser.parse_args(argv)

    try:
        report = build_benchmark_review_report(
            args.strategy_equity_csv,
            args.benchmark_csv,
            args.benchmark_metadata,
            strategy_date_column=args.strategy_date_column,
            strategy_value_column=args.strategy_value_column,
            benchmark_date_column=args.benchmark_date_column,
            benchmark_value_column=args.benchmark_value_column,
            periods_per_year=args.periods_per_year,
            block_size=args.block_size,
            n_bootstrap=args.n_bootstrap,
            random_seed=args.random_seed,
        )
        output = write_benchmark_review_report(report, args.output_dir)
    except (BenchmarkReviewInputError, OSError) as exc:
        print(f"Benchmark review input error: {exc}", file=sys.stderr)
        return 2

    print(f"Benchmark review status: {report.status}")
    print(f"Reports written to: {output.resolve()}")
    return 2 if report.status == "BLOCK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
