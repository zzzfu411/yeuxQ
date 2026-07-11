"""Run source-first OHLCV closeout into guarded offline intake."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.ohlcv_intake_closeout import run_ohlcv_intake_closeout


def main() -> None:
    parser = argparse.ArgumentParser(description="Close raw OHLCV discovery into guarded offline intake.")
    parser.add_argument("--data-dir", default="data_exports")
    parser.add_argument("--report-dir", default="results/first_million")
    parser.add_argument("--config", default="config/research_recent.yaml")
    parser.add_argument("--cache", default=None)
    parser.add_argument("--raw-bars-csv", default=None)
    parser.add_argument("--source-qa-answers", default=None)
    parser.add_argument("--source-qa-evidence-manifest", default=None)
    parser.add_argument("--require-source-qa-evidence-manifest", action="store_true", default=True)
    parser.add_argument("--no-require-source-qa-evidence-manifest", action="store_false", dest="require_source_qa_evidence_manifest")
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument("--min-trading-days", type=int, default=240)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--max-staleness-days", type=int, default=10)
    parser.add_argument("--min-coverage-ratio", type=float, default=0.95)
    parser.add_argument(
        "--no-run-guarded-intake",
        action="store_true",
        help="Only write closeout preflight evidence; do not call offline_data_intake.",
    )
    args = parser.parse_args()

    closeout = run_ohlcv_intake_closeout(
        data_dir=args.data_dir,
        report_dir=args.report_dir,
        config_path=args.config,
        cache_path=args.cache,
        raw_bars_csv=args.raw_bars_csv,
        source_qa_answers=args.source_qa_answers,
        source_qa_evidence_manifest=args.source_qa_evidence_manifest,
        require_source_qa_evidence_manifest=args.require_source_qa_evidence_manifest,
        min_symbols=args.min_symbols,
        min_trading_days=args.min_trading_days,
        as_of=args.as_of,
        encoding=args.encoding,
        max_staleness_days=args.max_staleness_days,
        min_coverage_ratio=args.min_coverage_ratio,
        run_guarded_intake=not args.no_run_guarded_intake,
    )
    logger.info("OHLCV intake closeout decision: {}", closeout.decision)
    logger.info("OHLCV intake closeout written to {}", Path(args.report_dir).resolve())
    if closeout.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
