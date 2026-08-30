"""Materialize one frozen prospective trial into a new post-holdout cache."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from quantify.research.prospective_execution_cache_materialization import (
    ARTIFACT_FILENAME,
    ProspectiveExecutionCacheMaterializationError,
    materialize_prospective_execution_cache,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "After the sealed holdout, verify all retained evidence and atomically rebuild "
            "a new lineage-aware execution cache. No strategy or broker operation is run."
        )
    )
    parser.add_argument("--packet-dir", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--quarantine-root", required=True, type=Path)
    parser.add_argument("--source-qa-checklist", required=True, type=Path)
    parser.add_argument("--source-qa-answers", required=True, type=Path)
    parser.add_argument("--source-qa-evidence-manifest", required=True, type=Path)
    parser.add_argument("--calendar-csv", required=True, type=Path)
    parser.add_argument("--calendar-metadata", required=True, type=Path)
    parser.add_argument("--benchmark-csv", required=True, type=Path)
    parser.add_argument("--benchmark-metadata", required=True, type=Path)
    parser.add_argument("--membership-csv", required=True, type=Path)
    parser.add_argument("--membership-metadata", required=True, type=Path)
    parser.add_argument("--minimum-members-per-snapshot", type=int, default=700)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        report = materialize_prospective_execution_cache(
            packet_dir=args.packet_dir,
            registry_path=args.registry,
            quarantine_root=args.quarantine_root,
            source_qa_checklist=args.source_qa_checklist,
            source_qa_answers=args.source_qa_answers,
            source_qa_evidence_manifest=args.source_qa_evidence_manifest,
            calendar_csv=args.calendar_csv,
            calendar_metadata=args.calendar_metadata,
            benchmark_csv=args.benchmark_csv,
            benchmark_metadata=args.benchmark_metadata,
            membership_csv=args.membership_csv,
            membership_metadata=args.membership_metadata,
            minimum_members_per_snapshot=args.minimum_members_per_snapshot,
            output_dir=args.output_dir,
        )
    except (OSError, ProspectiveExecutionCacheMaterializationError, ValueError) as exc:
        print(f"Materialization failed closed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(f"Prospective execution-cache materialization: {report.status}")
    print(f"Materialized: {report.materialized}")
    print("Network access: False")
    print("Holdout analysis performed: False")
    print("Broker access: False")
    if report.materialized:
        print(f"Artifact: {(args.output_dir / ARTIFACT_FILENAME).resolve()}")
        print(f"Execution cache: {report.output_cache['path']}")
    else:
        for blocker in report.blockers:
            print(f"BLOCK: {blocker}")
    return 0 if report.sufficient else 2


if __name__ == "__main__":
    raise SystemExit(main())
