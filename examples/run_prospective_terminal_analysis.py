"""Run one admitted frozen prospective terminal analysis and append its result."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from quantify.research.prospective_terminal_analysis import (
    ARTIFACT_FILENAME,
    ProspectiveTerminalAnalysisError,
    run_prospective_terminal_analysis,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the packet-bound candidate on its frozen holdout exactly once after "
            "admission PASS, publish evidence, and append one registry result."
        )
    )
    parser.add_argument("--packet-dir", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--materialization-artifact", required=True, type=Path)
    parser.add_argument("--benchmark-csv", required=True, type=Path)
    parser.add_argument("--benchmark-metadata", required=True, type=Path)
    parser.add_argument("--membership-csv", required=True, type=Path)
    parser.add_argument("--membership-metadata", required=True, type=Path)
    parser.add_argument("--minimum-members-per-snapshot", type=int, default=700)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        report = run_prospective_terminal_analysis(
            packet_dir=args.packet_dir,
            registry_path=args.registry,
            materialization_artifact=args.materialization_artifact,
            benchmark_csv=args.benchmark_csv,
            benchmark_metadata=args.benchmark_metadata,
            membership_csv=args.membership_csv,
            membership_metadata=args.membership_metadata,
            minimum_members_per_snapshot=args.minimum_members_per_snapshot,
            output_dir=args.output_dir,
        )
    except (OSError, RuntimeError, ProspectiveTerminalAnalysisError, ValueError) as exc:
        print(f"Prospective terminal analysis failed closed: {exc}", file=sys.stderr)
        return 2
    print(f"Prospective terminal execution: {report.status}")
    print(f"Completed: {report.completed}")
    print(f"Frozen trial decision: {report.decision}")
    print("Network access: False")
    print("Broker access: False")
    if report.completed:
        print(f"Artifact: {(args.output_dir / ARTIFACT_FILENAME).resolve()}")
    else:
        for blocker in report.blockers:
            print(f"BLOCK: {blocker}")
    return 0 if report.completed and report.decision != "BLOCK" else 2


if __name__ == "__main__":
    raise SystemExit(main())
