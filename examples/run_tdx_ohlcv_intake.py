"""Run guarded local TongDaXin OHLCV intake workflow."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.tdx_intake import run_tdx_ohlcv_intake


def main() -> None:
    parser = argparse.ArgumentParser(description="Run guarded TDX OHLCV intake workflow.")
    parser.add_argument("--input-dir", required=True, help="TongDaXin vipdoc, lday directory, or .day file")
    parser.add_argument("--data-dir", default="data_exports")
    parser.add_argument("--output-dir", default="results/first_million")
    parser.add_argument("--config", default="config/research_recent.yaml")
    parser.add_argument("--source-qa-answers", default=None)
    parser.add_argument("--source-qa-evidence-manifest", default=None)
    parser.add_argument("--require-source-qa-evidence-manifest", action="store_true")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument("--min-trading-days", type=int, default=240)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument(
        "--run-guarded-intake",
        action="store_true",
        help="Continue into offline_data_intake after conversion and package checks.",
    )
    args = parser.parse_args()

    report = run_tdx_ohlcv_intake(
        input_dir=args.input_dir,
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        config_path=args.config,
        source_qa_answers=args.source_qa_answers,
        source_qa_evidence_manifest=args.source_qa_evidence_manifest,
        require_source_qa_evidence_manifest=args.require_source_qa_evidence_manifest,
        start=args.start,
        end=args.end,
        min_symbols=args.min_symbols,
        min_trading_days=args.min_trading_days,
        as_of=args.as_of,
        encoding=args.encoding,
        run_guarded_intake=args.run_guarded_intake,
    )
    logger.info("TDX OHLCV intake status: {}", report.status)
    logger.info("TDX OHLCV intake written to {}", Path(args.output_dir).resolve())
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
