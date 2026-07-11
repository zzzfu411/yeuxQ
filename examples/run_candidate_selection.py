"""Run multiple strategy candidates and score them against the capital goal."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from loguru import logger

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.goal import CapitalGoal
from quantify.research.candidate_cli_guard import CandidateCliGateError, enforce_candidate_cli_gate
from quantify.research.candidates import (
    candidate_specs_for_names,
    run_candidate_selection,
    write_candidate_selection_report,
)
from quantify.research.demo_data import seed_demo_data
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strategy candidate selection.")
    parser.add_argument("--config", default="config/research.yaml", help="YAML config path")
    parser.add_argument("--cache", default=None, help="Override config data.cache_path")
    parser.add_argument("--output-dir", required=True, help="Output directory for candidate reports")
    parser.add_argument("--starting-capital", type=float, default=100_000.0)
    parser.add_argument("--target-capital", type=float, default=1_000_000.0)
    parser.add_argument("--years", type=float, default=8.0)
    parser.add_argument("--max-drawdown-budget", type=float, default=0.20)
    parser.add_argument("--candidate", action="append", default=None, help="Restrict selection to a candidate name")
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

    out = Path(args.output_dir)
    goal = CapitalGoal(
        starting_capital=args.starting_capital,
        target_capital=args.target_capital,
        years=args.years,
        max_drawdown_budget=args.max_drawdown_budget,
    )
    audit = _read_json(out / "data_audit.json")
    robustness = _read_json(out / "robustness_report.json")
    market_regime = _read_first_json(out / "market_regime.json", out / "weekly" / "market_regime.json")
    candidate_walk_forward = _read_json(out / "candidate_walk_forward_report.json")
    candidate_regime_validation = _read_json(out / "candidate_regime_validation_report.json")
    report = run_candidate_selection(
        provider,
        cfg,
        goal=goal,
        data_audit_status=str(audit.get("status", "UNKNOWN")),
        robustness_status=str(robustness.get("status", "UNKNOWN")),
        market_regime=market_regime,
        candidate_walk_forward=candidate_walk_forward,
        candidate_regime_validation=candidate_regime_validation,
        specs=candidate_specs_for_names(cfg, args.candidate),
    )
    write_candidate_selection_report(report, out)
    logger.info("Candidate selection status: {}", report.status)
    logger.info("Selected candidate: {}", report.selected_candidate or "none")
    logger.info("Top candidate: {}", report.top_candidate or "none")
    logger.info("Candidate selection written to {}", out.resolve())


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_first_json(*paths: Path) -> dict:
    for path in paths:
        payload = _read_json(path)
        if payload:
            return payload
    return {}


def _load_config(path: str, *, cache_path: str | None = None):
    cfg = load_config(path)
    if cache_path is None:
        return cfg
    payload = cfg.to_dict()
    data = dict(payload.get("data", {}))
    data["cache_path"] = cache_path
    return type(cfg)({**payload, "data": data})


def _single_candidate(candidates: list[str] | None) -> str | None:
    requested = [item for item in candidates or [] if item]
    return requested[0] if len(requested) == 1 else None


if __name__ == "__main__":
    main()
