"""Freeze and optionally append a research-only prospective trial packet."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from quantify.research.prospective_trial_packet import (
    append_packet_preregistration,
    build_prospective_trial_packet,
    write_prospective_trial_packet,
)
from quantify.research.trial_registry import TrialRegistryError


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze a candidate protocol before the prospective holdout begins."
    )
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--base-config", required=True, type=Path)
    parser.add_argument("--development-cache", required=True, type=Path)
    parser.add_argument("--execution-cache", required=True, type=Path)
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--train-start", required=True)
    parser.add_argument("--train-end", required=True)
    parser.add_argument("--selection-start", required=True)
    parser.add_argument("--selection-end", required=True)
    parser.add_argument("--test-start", required=True)
    parser.add_argument("--test-end", required=True)
    parser.add_argument("--execution-results-dir", default="results/prospective/guard_v1")
    parser.add_argument("--market-evidence-preflight", type=Path)
    parser.add_argument("--code-file", action="append", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--append-registry", action="store_true")
    parser.add_argument("--registry", type=Path)
    args = parser.parse_args()

    if args.append_registry and args.registry is None:
        parser.error("--registry is required with --append-registry")

    try:
        packet = build_prospective_trial_packet(
            plan_path=args.plan,
            base_config_path=args.base_config,
            development_cache_path=args.development_cache,
            execution_cache_path=args.execution_cache,
            trial_id=args.trial_id,
            candidate=args.candidate,
            train_start=args.train_start,
            train_end=args.train_end,
            selection_start=args.selection_start,
            selection_end=args.selection_end,
            test_start=args.test_start,
            test_end=args.test_end,
            execution_results_dir=args.execution_results_dir,
            market_evidence_preflight=args.market_evidence_preflight,
            code_paths=args.code_file,
        )
        output = write_prospective_trial_packet(packet, args.output_dir)
        response: dict[str, object] = {
            "status": packet.status,
            "packet_sha256": packet.packet_sha256,
            "registry_append_allowed": packet.registry_append_allowed,
            "execution_allowed": packet.execution_allowed,
            "output_dir": str(output.resolve()),
        }
        if args.append_registry:
            event = append_packet_preregistration(packet, args.registry)
            response["registry_event"] = event.to_dict()
            (output / "trial_registry_append.json").write_text(
                json.dumps(event.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    except (OSError, TypeError, ValueError, TrialRegistryError) as exc:
        raise SystemExit(f"Prospective trial packet failed: {type(exc).__name__}: {exc}") from exc

    print(json.dumps(response, ensure_ascii=False, indent=2))
    if packet.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
