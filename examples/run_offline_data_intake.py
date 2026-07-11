"""Run the guarded offline CSV intake pipeline for recent A-share data."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.offline_intake import run_offline_data_intake


def main() -> None:
    parser = argparse.ArgumentParser(description="Run guarded offline CSV data intake.")
    parser.add_argument("--data-dir", default="data_exports", help="Directory containing CSV exports")
    parser.add_argument("--config", default="config/research_recent.yaml", help="Research config path")
    parser.add_argument("--cache", default=None, help="Override config data.cache_path")
    parser.add_argument("--output-dir", default="results/import/offline_intake")
    parser.add_argument("--start", default=None, help="Override research start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="Override research end date YYYY-MM-DD")
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument("--min-trading-days", type=int, default=240)
    parser.add_argument("--as-of", default=None, help="Bootstrap as-of date YYYY-MM-DD")
    parser.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="CSV encoding; use auto for GBK/GB18030 exports with Chinese column names.",
    )
    parser.add_argument(
        "--raw-bars-csv",
        default=None,
        help=(
            "Optional raw broker/vendor bars CSV to normalize into data-dir/bars.csv "
            "before intake; common Chinese OHLCV headers are accepted."
        ),
    )
    parser.add_argument("--source-vendor", default=None, help="Data vendor or broker name for source QA answers")
    parser.add_argument("--source-terminal", default=None, help="Terminal or product name for source QA answers")
    parser.add_argument("--source-operator", default=None, help="Export operator for source QA answers")
    parser.add_argument("--source-exported-at", default=None, help="Local export timestamp for source QA answers")
    parser.add_argument("--source-price-adjustment", default=None, help="raw/qfq/hfq as exported")
    parser.add_argument("--source-price-adjustment-evidence", default=None)
    parser.add_argument("--source-license-scope", default="research and paper trading only")
    parser.add_argument("--source-license-evidence", default=None)
    parser.add_argument(
        "--source-point-in-time-evidence",
        default=None,
        help="Vendor PIT evidence, or note that non-PIT fields remain research-only",
    )
    parser.add_argument("--source-reviewed-by", default=None)
    parser.add_argument("--source-reviewed-at", default=None)
    parser.add_argument("--source-known-limitations", default="")
    parser.add_argument(
        "--source-qa-checklist",
        default=None,
        help="Optional data_source_qa.json path; defaults to data-dir if present",
    )
    parser.add_argument(
        "--source-qa-answers",
        default=None,
        help="Optional filled data_source_qa_answers.json path",
    )
    parser.add_argument(
        "--source-qa-evidence-manifest",
        default=None,
        help="Optional source_qa_evidence_manifest.json path",
    )
    parser.add_argument("--require-source-qa-evidence-manifest", action="store_true")
    args = parser.parse_args()

    report = run_offline_data_intake(
        data_dir=args.data_dir,
        config_path=args.config,
        cache_path=args.cache,
        output_dir=args.output_dir,
        start=args.start,
        end=args.end,
        min_symbols=args.min_symbols,
        min_trading_days=args.min_trading_days,
        as_of=args.as_of,
        encoding=args.encoding,
        raw_bars_csv=args.raw_bars_csv,
        source_vendor=args.source_vendor,
        source_terminal=args.source_terminal,
        source_operator=args.source_operator,
        source_exported_at=args.source_exported_at,
        source_price_adjustment=args.source_price_adjustment,
        source_price_adjustment_evidence=args.source_price_adjustment_evidence,
        source_license_scope=args.source_license_scope,
        source_license_evidence=args.source_license_evidence,
        source_point_in_time_evidence=args.source_point_in_time_evidence,
        source_reviewed_by=args.source_reviewed_by,
        source_reviewed_at=args.source_reviewed_at,
        source_known_limitations=args.source_known_limitations,
        source_qa_checklist=args.source_qa_checklist,
        source_qa_answers=args.source_qa_answers,
        source_qa_evidence_manifest=args.source_qa_evidence_manifest,
        require_source_qa_evidence_manifest=args.require_source_qa_evidence_manifest,
    )
    logger.info("Offline data intake status: {}", report.status)
    logger.info("Offline data intake report written to {}", Path(args.output_dir).resolve())
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
