"""Reverify a post-holdout prospective execution-cache materialization."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from quantify.research.prospective_execution_cache_materialization import (
    build_prospective_execution_cache_materialization_verification,
    write_prospective_execution_cache_materialization_verification,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only verification of the one-time claim, packet, registry, evidence, "
            "sealed replay manifest, and materialized SQLite cache."
        )
    )
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--packet-dir", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        verification = build_prospective_execution_cache_materialization_verification(
            args.artifact,
            packet_dir=args.packet_dir,
            registry_path=args.registry,
        )
        output = write_prospective_execution_cache_materialization_verification(
            verification,
            args.output_dir,
        )
    except (OSError, ValueError) as exc:
        print(f"Materialization verification failed closed: {exc}", file=sys.stderr)
        return 2
    print(f"Materialization verification: {verification.status}")
    print("Network access: False")
    print("Broker access: False")
    print(
        "Report: "
        f"{(output / 'prospective_execution_cache_materialization_verification.json').resolve()}"
    )
    return 0 if verification.sufficient else 2


if __name__ == "__main__":
    raise SystemExit(main())
