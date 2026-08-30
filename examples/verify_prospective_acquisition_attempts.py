"""Verify the append-only prospective provider-attempt journal."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from quantify.data.prospective_acquisition_journal import (
    ProspectiveAcquisitionJournalError,
    verify_prospective_acquisition_attempts,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify prospective acquisition-attempt event hashes and referenced reports "
            "without provider, cache-write, holdout-analysis, or broker access."
        )
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        events = verify_prospective_acquisition_attempts(args.output_dir)
    except ProspectiveAcquisitionJournalError as exc:
        print(f"Prospective acquisition-attempt journal: BLOCK ({exc})", file=sys.stderr)
        return 2
    print("Prospective acquisition-attempt journal: PASS")
    print(f"Attempt events: {len(events)}")
    print(f"Tail hash: {events[-1]['event_hash'] if events else 'none'}")
    print("Network access: False")
    print("Holdout analysis allowed: False")
    print("Broker access: False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
