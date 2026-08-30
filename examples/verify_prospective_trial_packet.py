"""Verify a frozen prospective packet against files, cache prefix, and registry."""
from __future__ import annotations

import argparse
from pathlib import Path

from quantify.research.prospective_trial_packet import (
    build_prospective_trial_packet_verification,
    write_prospective_trial_packet_verification,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify all local guard-v1 packet bindings.")
    parser.add_argument("--packet-dir", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    verification = build_prospective_trial_packet_verification(
        args.packet_dir,
        args.registry,
        workspace_root=args.workspace_root,
    )
    output = write_prospective_trial_packet_verification(
        verification,
        args.output_dir or args.packet_dir,
    )
    print(f"Prospective packet integrity: {verification.status}")
    print(f"Report: {(output / 'prospective_trial_packet_verification.json').resolve()}")
    if verification.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
