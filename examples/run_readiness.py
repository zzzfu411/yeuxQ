"""Create approval records and evaluate micro-live readiness."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from loguru import logger

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.readiness import (
    build_manual_target_plan,
    write_approval_record,
    write_manual_target_plan,
    write_readiness_outputs,
)
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate micro-live readiness.")
    parser.add_argument("--report-dir", required=True, help="Research report directory")
    parser.add_argument("--approved-by", default="", help="Create/update approval_record.json")
    parser.add_argument("--approval-notes", default="", help="Approval notes")
    parser.add_argument(
        "--build-target-plan",
        action="store_true",
        help="Build target_portfolio.csv and manual_trade_sheet.csv before readiness evaluation.",
    )
    parser.add_argument("--config", default="config/research.yaml", help="YAML config for target plan generation")
    parser.add_argument("--cache", default=None, help="Override config data.cache_path for target plan generation")
    parser.add_argument("--as-of", default=None, help="Target plan date YYYY-MM-DD; defaults to latest cached day")
    parser.add_argument("--candidate", default=None, help="Candidate strategy name for target plan generation")
    parser.add_argument("--capital", type=float, default=None, help="Manual planning capital")
    parser.add_argument("--cash-buffer-pct", type=float, default=0.05)
    parser.add_argument(
        "--current-positions",
        default=None,
        help="Optional paper_positions.csv path; defaults to report-dir/paper_positions.csv when present.",
    )
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    if args.build_target_plan:
        cfg = load_config(args.config)
        provider = DataProvider(BarStorage(args.cache or cfg.data.cache_path))
        plan = build_manual_target_plan(
            provider,
            cfg,
            as_of=args.as_of,
            candidate=args.candidate,
            capital=args.capital,
            cash_buffer_pct=args.cash_buffer_pct,
            current_positions=_read_positions(args.current_positions, report_dir),
        )
        write_manual_target_plan(plan, report_dir)
        logger.info("Manual target plan written to {}", report_dir.resolve())

    if args.approved_by:
        path = write_approval_record(
            report_dir,
            approved_by=args.approved_by,
            approval_notes=args.approval_notes,
        )
        logger.info("Approval record written to {}", path.resolve())
    out = write_readiness_outputs(report_dir)
    logger.info("Micro-live readiness outputs written to {}", out.resolve())


def _read_positions(path: str | None, report_dir: Path) -> pd.DataFrame | None:
    candidate = Path(path) if path else report_dir / "paper_positions.csv"
    if not candidate.exists() or candidate.stat().st_size == 0:
        return None
    return pd.read_csv(candidate)


if __name__ == "__main__":
    main()
