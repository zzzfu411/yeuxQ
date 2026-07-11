"""Build the real-data handoff checklist for recent A-share research."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.real_data_handoff import (
    build_real_data_handoff_checklist,
    write_real_data_handoff_checklist,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build real-data handoff checklist.")
    parser.add_argument("--data-dir", default="data_exports", help="Offline CSV export directory")
    parser.add_argument("--config", default="config/research_recent.yaml", help="Recent A-share config")
    parser.add_argument("--source-qa-answers", default=None, help="Filled data_source_qa_answers.json")
    parser.add_argument("--output-dir", default="results/first_million")
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument("--min-trading-days", type=int, default=240)
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    parser.add_argument("--encoding", default="utf-8-sig")
    args = parser.parse_args()

    checklist = build_real_data_handoff_checklist(
        data_dir=args.data_dir,
        config_path=args.config,
        source_qa_answers=args.source_qa_answers,
        min_symbols=args.min_symbols,
        min_trading_days=args.min_trading_days,
        as_of=args.as_of,
        encoding=args.encoding,
    )
    out = write_real_data_handoff_checklist(checklist, Path(args.output_dir))
    logger.info("Real-data handoff status: {}", checklist.status)
    logger.info("Real-data handoff checklist written to {}", out.resolve())
    if checklist.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
