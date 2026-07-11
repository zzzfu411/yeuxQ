"""Build an action plan for closing first-million data evidence gaps."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.gap_action_plan import build_data_gap_action_plan, write_data_gap_action_plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a data gap action plan.")
    parser.add_argument("--data-dir", default="data_exports", help="Offline CSV export directory")
    parser.add_argument("--config", default="config/research_recent.yaml", help="Recent A-share config")
    parser.add_argument("--source-qa-answers", default=None, help="Filled data_source_qa_answers.json")
    parser.add_argument("--output-dir", default="results/first_million")
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    parser.add_argument("--encoding", default="utf-8-sig")
    args = parser.parse_args()

    plan = build_data_gap_action_plan(
        data_dir=args.data_dir,
        config_path=args.config,
        source_qa_answers=args.source_qa_answers,
        min_symbols=args.min_symbols,
        as_of=args.as_of,
        encoding=args.encoding,
    )
    out = write_data_gap_action_plan(plan, Path(args.output_dir))
    logger.info("Data gap action plan decision: {}", plan.decision)
    logger.info("Data gap action plan written to {}", out.resolve())
    if plan.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
