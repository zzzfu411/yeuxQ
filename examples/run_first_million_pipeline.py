"""Run the guarded first-million A-share research pipeline."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.ops.first_million import run_first_million_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run guarded first-million research pipeline.")
    parser.add_argument("--config", default="config/research_recent.yaml", help="Recent A-share config")
    parser.add_argument("--cache", default=None, help="Override config data.cache_path")
    parser.add_argument("--data-dir", default="data_exports", help="Offline CSV export directory")
    parser.add_argument("--output-dir", default="results/first_million")
    parser.add_argument("--source-qa-answers", default=None, help="Filled data_source_qa_answers.json")
    parser.add_argument(
        "--source-qa-worksheet",
        default=None,
        help="Filled data_source_qa_evidence_worksheet.csv/json to convert into answers before checks",
    )
    parser.add_argument(
        "--source-qa-evidence-manifest",
        default=None,
        help="Optional source_qa_evidence_manifest.json path",
    )
    parser.add_argument("--require-source-qa-evidence-manifest", action="store_true")
    parser.add_argument("--starting-capital", type=float, default=100_000.0)
    parser.add_argument("--target-capital", type=float, default=1_000_000.0)
    parser.add_argument("--years", type=float, default=8.0)
    parser.add_argument("--max-drawdown-budget", type=float, default=0.20)
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument("--min-trading-days", type=int, default=240)
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    parser.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="CSV encoding; use auto for GBK/GB18030 exports with Chinese column names.",
    )
    parser.add_argument(
        "--raw-bars-csv",
        default=None,
        help=(
            "Optional raw broker/vendor bars CSV to normalize before guarded intake; "
            "common Chinese OHLCV headers are accepted."
        ),
    )
    parser.add_argument("--source-vendor", default=None, help="Data vendor or broker name")
    parser.add_argument("--source-terminal", default=None, help="Terminal or product name")
    parser.add_argument("--source-operator", default=None, help="Export operator")
    parser.add_argument("--source-exported-at", default=None, help="Local export timestamp")
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
    parser.add_argument("--paper-state-dir", default=None)
    parser.add_argument(
        "--prepare-micro-live-readiness",
        action="store_true",
        help=(
            "When the weekly evidence stage runs, generate manual target portfolio, "
            "manual_trade_sheet, risk_budget, and micro_live_readiness artifacts. "
            "This never creates approval records or broker orders."
        ),
    )
    parser.add_argument("--micro-live-candidate", default=None, help="Candidate for manual target planning")
    parser.add_argument("--micro-live-capital", type=float, default=None, help="Capital for manual target planning")
    parser.add_argument("--micro-live-cash-buffer-pct", type=float, default=0.05)
    parser.add_argument(
        "--current-positions",
        default=None,
        help="Optional current paper_positions.csv for manual target planning",
    )
    parser.add_argument(
        "--latest-import-report",
        default="results/import/recent/data_import.json",
        help="Optional AKShare import attempt report to summarize in readiness",
    )
    parser.add_argument(
        "--provider-acquisition-ramp-report",
        default=None,
        help=(
            "Optional provider_acquisition_ramp.json to copy into the first-million report. "
            "This is route diagnostics only and cannot upgrade deterministic gates."
        ),
    )
    parser.add_argument(
        "--tdx-search-dir",
        action="append",
        default=None,
        help="Optional TongDaXin vipdoc or lday directory; can be supplied multiple times",
    )
    parser.add_argument(
        "--tdx-input-dir",
        default=None,
        help="Optional TongDaXin vipdoc/lday directory to convert into data_exports before checks",
    )
    parser.add_argument("--tdx-operator", default=None, help="Human operator who prepared TDX export")
    parser.add_argument("--tdx-exported-at", default=None, help="Local TDX export/conversion timestamp")
    parser.add_argument("--tdx-price-adjustment", default=None, help="raw/qfq/hfq as evidenced by TDX")
    parser.add_argument("--tdx-price-adjustment-evidence", default=None)
    parser.add_argument("--tdx-license-scope", default="research and paper trading only")
    parser.add_argument("--tdx-license-evidence", default=None)
    parser.add_argument(
        "--tdx-pit-fundamental-evidence",
        default=None,
        help="Separate PIT evidence if available; otherwise TDX stays OHLCV-only",
    )
    parser.add_argument("--tdx-reviewed-by", default=None)
    parser.add_argument("--tdx-reviewed-at", default=None)
    parser.add_argument("--tdx-known-limitations", default="")
    parser.add_argument(
        "--registry",
        default="results/strategy_registry/strategy_registry.json",
        help="Persistent strategy registry JSON path",
    )
    parser.add_argument("--no-registry", action="store_true")
    parser.add_argument(
        "--execute-candidate-experiment",
        action="store_true",
        help=(
            "Opt in to execute the PASS candidate experiment launch plan with the guarded "
            "research-only whitelist. Default is dry-run command validation."
        ),
    )
    args = parser.parse_args()

    result = run_first_million_pipeline(
        config_path=args.config,
        cache_path=args.cache,
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        source_qa_answers=args.source_qa_answers,
        source_qa_worksheet=args.source_qa_worksheet,
        source_qa_evidence_manifest=args.source_qa_evidence_manifest,
        require_source_qa_evidence_manifest=args.require_source_qa_evidence_manifest,
        starting_capital=args.starting_capital,
        target_capital=args.target_capital,
        years=args.years,
        max_drawdown_budget=args.max_drawdown_budget,
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
        paper_state_dir=Path(args.paper_state_dir) if args.paper_state_dir else None,
        prepare_micro_live_readiness=args.prepare_micro_live_readiness,
        micro_live_candidate=args.micro_live_candidate,
        micro_live_capital=args.micro_live_capital,
        micro_live_cash_buffer_pct=args.micro_live_cash_buffer_pct,
        current_positions_path=Path(args.current_positions) if args.current_positions else None,
        registry_path=None if args.no_registry else Path(args.registry),
        latest_import_report_path=args.latest_import_report,
        provider_acquisition_ramp_report_path=args.provider_acquisition_ramp_report,
        tdx_search_dirs=args.tdx_search_dir,
        tdx_input_dir=args.tdx_input_dir,
        tdx_operator=args.tdx_operator,
        tdx_exported_at=args.tdx_exported_at,
        tdx_price_adjustment=args.tdx_price_adjustment,
        tdx_price_adjustment_evidence=args.tdx_price_adjustment_evidence,
        tdx_license_scope=args.tdx_license_scope,
        tdx_license_evidence=args.tdx_license_evidence,
        tdx_pit_fundamental_evidence=args.tdx_pit_fundamental_evidence,
        tdx_reviewed_by=args.tdx_reviewed_by,
        tdx_reviewed_at=args.tdx_reviewed_at,
        tdx_known_limitations=args.tdx_known_limitations,
        execute_candidate_experiment=args.execute_candidate_experiment,
    )
    logger.info("First-million pipeline decision: {}", result.decision)
    logger.info("First-million pipeline written to {}", Path(args.output_dir).resolve())
    if result.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
