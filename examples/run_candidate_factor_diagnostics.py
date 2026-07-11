"""Run factor-component diagnostics for strategy candidates."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.research.candidate_cli_guard import CandidateCliGateError, enforce_candidate_cli_gate
from quantify.research.candidate_factor_diagnostics import (
    run_candidate_factor_diagnostics,
    write_candidate_factor_diagnostics_report,
)
from quantify.research.demo_data import seed_demo_data
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run candidate factor-component diagnostics.")
    parser.add_argument("--config", default="config/research.yaml", help="YAML config path")
    parser.add_argument("--cache", default=None, help="Override config data.cache_path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--train-days", type=int, default=120)
    parser.add_argument("--test-days", type=int, default=60)
    parser.add_argument("--step-days", type=int, default=60)
    parser.add_argument("--max-windows", type=int, default=None, help="Optional cap using the latest N windows")
    parser.add_argument(
        "--max-components",
        type=int,
        default=None,
        help="Optional cap on factor components for lightweight research triage",
    )
    parser.add_argument("--candidate", default=None, help="Optional candidate name to diagnose")
    parser.add_argument(
        "--gate-report-dir",
        default=None,
        help="Report directory containing PASS candidate_experiment_launch.json for guarded real-data runs",
    )
    args = parser.parse_args()

    cfg = _load_config(args.config, cache_path=args.cache)
    try:
        enforce_candidate_cli_gate(
            args.gate_report_dir,
            cfg=cfg,
            candidate=args.candidate,
            output_dir=args.output_dir,
        )
    except CandidateCliGateError as exc:
        logger.error("{}", exc)
        raise SystemExit(2) from exc
    storage = BarStorage(cfg.data.cache_path)
    provider = DataProvider(storage)
    if not provider.all_symbols() or not provider.trading_days(cfg.research.start, cfg.research.end):
        if not cfg.research.allow_demo_data:
            raise RuntimeError("No cached research data found and allow_demo_data=false.")
        seed_demo_data(storage, cfg.research.start, cfg.research.end)
    report = run_candidate_factor_diagnostics(
        provider,
        cfg,
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        max_windows=args.max_windows,
        max_components=args.max_components,
        candidate=args.candidate,
    )
    out = write_candidate_factor_diagnostics_report(report, Path(args.output_dir))
    logger.info("Candidate factor diagnostics status: {}", report.status)
    logger.info("Candidate factor diagnostics written to {}", out.resolve())


def _load_config(path: str, *, cache_path: str | None = None):
    cfg = load_config(path)
    if cache_path is None:
        return cfg
    payload = cfg.to_dict()
    data = dict(payload.get("data", {}))
    data["cache_path"] = cache_path
    return type(cfg)({**payload, "data": data})


if __name__ == "__main__":
    main()
