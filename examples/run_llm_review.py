"""Run an LLM-ready review for a research report directory.

Usage:
    uv run python examples/run_llm_review.py --report-dir results/research/<timestamp>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from loguru import logger

from quantify.llm import (
    LLMClient,
    LLMClientConfig,
    LLMReviewPromptBuilder,
    ReviewThresholds,
    review_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Review a research report before promotion.")
    parser.add_argument("--report-dir", required=True, help="Directory containing summary.json")
    parser.add_argument(
        "--stage",
        choices=["research", "paper", "micro_live_ready", "micro_live", "live"],
        default="paper",
        help="Promotion stage being considered",
    )
    parser.add_argument(
        "--allow-live-on-demo-data",
        action="store_true",
        help="Downgrade demo-data live review from BLOCK to WATCH. Not recommended.",
    )
    parser.add_argument(
        "--call-llm",
        action="store_true",
        help="Call an OpenAI-compatible advisory LLM. Offline prompt generation is the default.",
    )
    parser.add_argument(
        "--llm-output",
        default="llm_narrative.md",
        help="Filename for optional advisory LLM narrative output inside report-dir.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override OPENAI_MODEL for the optional advisory LLM call.",
    )
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    thresholds = ReviewThresholds(allow_live_on_demo_data=args.allow_live_on_demo_data)
    result = review_report(report_dir, intended_stage=args.stage, thresholds=thresholds)
    prompt_pack = LLMReviewPromptBuilder().build(result)

    (report_dir / "llm_review.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (report_dir / "llm_review.md").write_text(result.to_markdown(), encoding="utf-8")
    (report_dir / "llm_prompt.md").write_text(prompt_pack.to_markdown(), encoding="utf-8")

    if args.call_llm:
        client = LLMClient(LLMClientConfig.from_env(model=args.model))
        narrative = client.review(prompt_pack)
        (report_dir / args.llm_output).write_text(narrative.to_markdown(), encoding="utf-8")
        (report_dir / "llm_narrative.json").write_text(
            json.dumps(narrative.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if narrative.ok:
            logger.info("Wrote advisory LLM narrative to {}", (report_dir / args.llm_output).resolve())
        else:
            logger.warning("Advisory LLM call skipped/failed: {}", narrative.error)

    logger.info("LLM-ready review decision: {}", result.decision)
    logger.info("Wrote {}", (report_dir / "llm_review.md").resolve())
    logger.info("Wrote {}", (report_dir / "llm_prompt.md").resolve())


if __name__ == "__main__":
    main()
