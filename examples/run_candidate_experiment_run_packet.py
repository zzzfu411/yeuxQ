"""Write a research-only candidate experiment run packet."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.research.candidate_experiment_run_packet import (
    build_candidate_experiment_run_packet_from_report,
    write_candidate_experiment_run_packet,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Write candidate experiment run packet.")
    parser.add_argument("--report-dir", required=True, help="Directory with first-million artifacts")
    parser.add_argument("--config", default="config/research_recent.yaml", help="YAML config path")
    parser.add_argument("--candidate", default=None, help="Optional candidate name override")
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    parser.add_argument("--run-id", default=None, help="Optional stable experiment run id")
    parser.add_argument(
        "--allow-pit",
        action="store_true",
        help="Allow non-OHLCV candidates in the packet. Defaults to OHLCV-only.",
    )
    args = parser.parse_args()

    packet = build_candidate_experiment_run_packet_from_report(
        args.report_dir,
        config_path=args.config,
        candidate=args.candidate,
        as_of=args.as_of,
        run_id=args.run_id,
        ohlcv_only=not args.allow_pit,
    )
    out = write_candidate_experiment_run_packet(packet, Path(args.report_dir))
    logger.info("Candidate experiment run packet decision: {}", packet.decision)
    logger.info("Selected candidate: {}", packet.selected_candidate or "none")
    logger.info("Candidate experiment run packet written to {}", out.resolve())
    if packet.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
