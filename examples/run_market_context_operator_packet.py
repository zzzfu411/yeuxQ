"""Build the market-context operator packet for reviewed index evidence."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.market import (
    build_market_context_operator_packet,
    write_market_context_operator_packet,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build market-context operator packet.")
    parser.add_argument("--report-dir", default="results/first_million")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--as-of", default=None, help="Target evidence as-of date YYYY-MM-DD")
    parser.add_argument("--max-staleness-days", type=int, default=7)
    args = parser.parse_args()

    packet = build_market_context_operator_packet(
        report_dir=args.report_dir,
        as_of=args.as_of,
        max_staleness_days=args.max_staleness_days,
    )
    out = write_market_context_operator_packet(packet, Path(args.output_dir or args.report_dir))
    logger.info("Market context operator packet decision: {}", packet.decision)
    logger.info("Market context operator packet written to {}", out.resolve())
    if packet.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
