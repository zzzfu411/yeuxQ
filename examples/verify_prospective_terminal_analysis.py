"""Verify one published prospective terminal result without rerunning it."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from quantify.research.prospective_terminal_analysis import (
    build_prospective_terminal_analysis_verification,
    write_prospective_terminal_analysis_verification,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only verification of terminal evidence files, decision, one-time claim, "
            "materialized cache, frozen packet, receipt, and unique registry result."
        )
    )
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--packet-dir", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--materialization-artifact", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        verification = build_prospective_terminal_analysis_verification(
            args.artifact,
            packet_dir=args.packet_dir,
            registry_path=args.registry,
            materialization_artifact=args.materialization_artifact,
        )
        output = write_prospective_terminal_analysis_verification(
            verification,
            args.output_dir,
        )
    except (OSError, ValueError) as exc:
        print(f"Terminal result verification failed closed: {exc}", file=sys.stderr)
        return 2
    print(f"Prospective terminal result verification: {verification.status}")
    print(f"Frozen trial decision: {verification.decision}")
    print("Network access: False")
    print("Broker access: False")
    print(f"Report: {(output / 'prospective_terminal_analysis_verification.json').resolve()}")
    return 0 if verification.sufficient else 2


if __name__ == "__main__":
    raise SystemExit(main())
