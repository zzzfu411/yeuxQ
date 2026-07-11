"""Run walk-forward validation for all strategy candidates.

Usage:
    uv run python examples/run_candidate_walk_forward.py --config config/research.yaml --output-dir results/research/<timestamp>
"""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.research.candidate_cli_guard import CandidateCliGateError, enforce_candidate_cli_gate
from quantify.research.candidate_walk_forward import (
    run_candidate_walk_forward,
    write_candidate_walk_forward_report,
)
from quantify.research.candidates import candidate_specs_for_names
from quantify.research.demo_data import seed_demo_data
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run candidate walk-forward validation.")
    parser.add_argument("--config", default="config/research.yaml", help="YAML config path")
    parser.add_argument("--cache", default=None, help="Override config data.cache_path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--train-days", type=int, default=120)
    parser.add_argument("--test-days", type=int, default=60)
    parser.add_argument("--step-days", type=int, default=60)
    parser.add_argument("--max-windows", type=int, default=None, help="Optional cap using the latest N windows")
    parser.add_argument("--candidate", action="append", default=None, help="Restrict validation to a candidate name")
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
            candidate=_single_candidate(args.candidate),
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
    report = run_candidate_walk_forward(
        provider,
        cfg,
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        max_windows=args.max_windows,
        specs=candidate_specs_for_names(cfg, args.candidate),
    )
    out = write_candidate_walk_forward_report(report, Path(args.output_dir))
    logger.info("Candidate walk-forward status: {}", report.status)
    logger.info("Best candidate: {}", report.best_candidate)
    logger.info("Candidate walk-forward report written to {}", out.resolve())


def _single_candidate(candidates: list[str] | None) -> str | None:
    requested = [item for item in candidates or [] if item]
    return requested[0] if len(requested) == 1 else None


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
