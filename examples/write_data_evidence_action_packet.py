"""Write a focused packet for collecting real A-share data evidence."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.evidence_packet import (
    build_data_evidence_action_packet,
    write_data_evidence_action_packet,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a real-data evidence action packet.")
    parser.add_argument("--data-dir", default="data_exports", help="Offline CSV export directory")
    parser.add_argument("--config", default="config/research_recent.yaml", help="Recent A-share config")
    parser.add_argument("--source-qa-answers", default=None, help="Filled data_source_qa_answers.json")
    parser.add_argument("--output-dir", default="results/first_million")
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    parser.add_argument("--encoding", default="utf-8-sig")
    args = parser.parse_args()

    packet = build_data_evidence_action_packet(
        data_dir=args.data_dir,
        config_path=args.config,
        source_qa_answers=args.source_qa_answers,
        min_symbols=args.min_symbols,
        as_of=args.as_of,
        encoding=args.encoding,
    )
    out = write_data_evidence_action_packet(packet, Path(args.output_dir))
    logger.info("Data evidence action packet decision: {}", packet.decision)
    logger.info("Data evidence action packet written to {}", out.resolve())
    if packet.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
