"""Recompute dynamic admission before opening a frozen prospective holdout."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from quantify.research.prospective_trial_admission import (
    build_prospective_trial_admission,
    write_prospective_trial_admission,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reverify a frozen trial, source lineage, market evidence, registry state, "
            "time seal, and terminal cache coverage without running the strategy."
        )
    )
    parser.add_argument("--packet-dir", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--benchmark-csv", required=True, type=Path)
    parser.add_argument("--benchmark-metadata", required=True, type=Path)
    parser.add_argument("--membership-csv", required=True, type=Path)
    parser.add_argument("--membership-metadata", required=True, type=Path)
    parser.add_argument(
        "--materialization-artifact",
        type=Path,
        help=(
            "Required when the frozen packet registered its development cache as the "
            "execution cache; must be the verified post-holdout materialization JSON."
        ),
    )
    parser.add_argument("--minimum-members-per-snapshot", type=int, default=700)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    report = build_prospective_trial_admission(
        packet_dir=args.packet_dir,
        registry_path=args.registry,
        benchmark_csv=args.benchmark_csv,
        benchmark_metadata=args.benchmark_metadata,
        membership_csv=args.membership_csv,
        membership_metadata=args.membership_metadata,
        materialization_artifact=args.materialization_artifact,
        minimum_members_per_snapshot=args.minimum_members_per_snapshot,
    )
    try:
        output = write_prospective_trial_admission(report, args.output_dir)
    except OSError as exc:
        print(f"Prospective trial admission output error: {exc}", file=sys.stderr)
        return 2

    print(f"Prospective trial admission status: {report.status}")
    print(f"Phase: {report.phase}")
    print(f"Collection ready: {report.collection_ready}")
    print(f"Terminal analysis allowed: {report.terminal_analysis_allowed}")
    print(f"Reports written to: {output.resolve()}")
    return 0 if report.sufficient else 2


if __name__ == "__main__":
    raise SystemExit(main())
