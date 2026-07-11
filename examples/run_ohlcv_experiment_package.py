"""Preflight the OHLCV-only experiment package for guarded research."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.ohlcv_experiment_package import (
    build_ohlcv_experiment_package_preflight,
    write_ohlcv_experiment_package_preflight,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build OHLCV-only experiment package preflight.")
    parser.add_argument("--data-dir", default="data_exports", help="Offline CSV export directory")
    parser.add_argument("--report-dir", default="results/first_million", help="First-million report directory")
    parser.add_argument("--config", default="config/research_recent.yaml", help="Recent A-share config")
    parser.add_argument("--source-qa-answers", default=None, help="Filled data_source_qa_answers.json")
    parser.add_argument(
        "--source-qa-evidence-manifest",
        default=None,
        help="Optional source_qa_evidence_manifest.json path",
    )
    parser.add_argument(
        "--require-source-qa-evidence-manifest",
        action="store_true",
        help="Require retained source QA evidence attachments to pass strict review",
    )
    parser.add_argument("--output-dir", default=None, help="Output directory; defaults to --report-dir")
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument("--min-trading-days", type=int, default=240)
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    parser.add_argument("--encoding", default="utf-8-sig")
    args = parser.parse_args()

    preflight = build_ohlcv_experiment_package_preflight(
        data_dir=args.data_dir,
        report_dir=args.report_dir,
        config_path=args.config,
        source_qa_answers=args.source_qa_answers,
        source_qa_evidence_manifest=args.source_qa_evidence_manifest,
        require_source_qa_evidence_manifest=args.require_source_qa_evidence_manifest,
        min_symbols=args.min_symbols,
        min_trading_days=args.min_trading_days,
        as_of=args.as_of,
        encoding=args.encoding,
    )
    out = write_ohlcv_experiment_package_preflight(preflight, Path(args.output_dir or args.report_dir))
    logger.info("OHLCV experiment package decision: {}", preflight.decision)
    logger.info("OHLCV experiment package preflight written to {}", out.resolve())
    if preflight.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
