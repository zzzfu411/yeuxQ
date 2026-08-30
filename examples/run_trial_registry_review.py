"""Build the downstream review for an append-only research trial registry."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path

from quantify.research.trial_registry_review import (
    build_trial_registry_review,
    write_trial_registry_review,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bind a verified preregistered trial to current research artifacts."
    )
    parser.add_argument("--registry", required=True, type=Path, help="Canonical trial JSONL path")
    parser.add_argument("--report-dir", required=True, type=Path, help="Current report directory")
    parser.add_argument(
        "--selected-candidate",
        default=None,
        help="Candidate to review; defaults to candidate_selection.json selected_candidate",
    )
    parser.add_argument(
        "--trial-id",
        default=None,
        help="Review this exact trial, including an unselected falsification trial.",
    )
    args = parser.parse_args(argv)

    if not args.registry.is_file():
        parser.error(f"--registry must be an existing file: {args.registry}")
    if not args.report_dir.is_dir():
        parser.error(f"--report-dir must be an existing directory: {args.report_dir}")

    review = build_trial_registry_review(
        args.registry,
        args.report_dir,
        selected_candidate=args.selected_candidate,
        trial_id=args.trial_id,
    )
    out = write_trial_registry_review(review, args.report_dir)
    print(
        json.dumps(
            {
                "artifact_type": review.artifact_type,
                "schema_version": review.schema_version,
                "status": review.status,
                "selected_candidate": review.selected_candidate,
                "matched_trial_id": review.matched_trial_id,
                "matched_result_id": review.matched_result_id,
                "blocker_count": len(review.blockers),
                "can_upgrade_deterministic_gate": review.can_upgrade_deterministic_gate,
                "json_path": str(out / "trial_registry_review.json"),
                "markdown_path": str(out / "trial_registry_review.md"),
            },
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 2 if review.status == "BLOCK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
