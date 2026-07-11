"""Run a research-only candidate precheck without granting promotion rights.

This command intentionally does not accept --gate-report-dir and does not call
the guarded launch gate. It is for non-promotional research triage only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from loguru import logger

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.goal import CapitalGoal
from quantify.research.candidate_factor_diagnostics import (
    run_candidate_factor_diagnostics,
    write_candidate_factor_diagnostics_report,
)
from quantify.research.candidate_next_experiments import (
    CandidateReportBundle,
    build_candidate_next_experiments_report,
    write_candidate_next_experiments_report,
)
from quantify.research.candidate_precheck import (
    build_candidate_research_precheck_report,
    write_candidate_research_precheck_report,
)
from quantify.research.candidate_walk_forward import (
    run_candidate_walk_forward,
    write_candidate_walk_forward_report,
)
from quantify.research.candidates import (
    CandidateSpec,
    candidate_specs_for_names,
    run_candidate_selection,
    write_candidate_selection_report,
)
from quantify.research.demo_data import seed_demo_data
from quantify.research.regime_validation import (
    run_candidate_regime_validation,
    write_candidate_regime_validation_report,
)
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run research-only candidate precheck.")
    parser.add_argument("--config", default="config/research.yaml", help="YAML config path")
    parser.add_argument("--cache", default=None, help="Override config data.cache_path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--candidate", action="append", default=None, help="Restrict precheck to a candidate name")
    parser.add_argument("--train-days", type=int, default=120)
    parser.add_argument("--test-days", type=int, default=60)
    parser.add_argument("--step-days", type=int, default=60)
    parser.add_argument(
        "--max-windows",
        type=int,
        default=3,
        help="Cap precheck to the latest N windows; use 0 for all windows",
    )
    parser.add_argument("--starting-capital", type=float, default=100_000.0)
    parser.add_argument("--target-capital", type=float, default=1_000_000.0)
    parser.add_argument("--years", type=float, default=8.0)
    parser.add_argument("--max-drawdown-budget", type=float, default=0.20)
    parser.add_argument(
        "--full-sample-selection",
        action="store_true",
        help="Run candidate_selection over the full configured sample instead of the latest precheck window.",
    )
    parser.add_argument(
        "--include-factor-diagnostics",
        action="store_true",
        help="Also run slower factor-component diagnostics.",
    )
    parser.add_argument(
        "--factor-max-components",
        type=int,
        default=None,
        help="Optional cap on factor components when --include-factor-diagnostics is used.",
    )
    parser.add_argument(
        "--include-regime-validation",
        action="store_true",
        help="Also run regime-stratified validation using the generated walk-forward windows.",
    )
    args = parser.parse_args()

    cfg = _load_config(args.config, cache_path=args.cache)
    specs = _candidate_specs_or_exit(cfg, args.candidate)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    provider = _provider(cfg)
    logger.info("Research-only candidate precheck candidates: {}", ", ".join(spec.name for spec in specs))
    max_windows = args.max_windows or None
    walk_forward = run_candidate_walk_forward(
        provider,
        cfg,
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        max_windows=max_windows,
        specs=specs,
    )
    write_candidate_walk_forward_report(walk_forward, output_dir)

    generated = [
        "candidate_walk_forward_report.json",
        "candidate_walk_forward_report.md",
    ]
    factor_diagnostics = None
    if args.include_factor_diagnostics:
        factor_diagnostics = run_candidate_factor_diagnostics(
            provider,
            cfg,
            train_days=args.train_days,
            test_days=args.test_days,
            step_days=args.step_days,
            max_windows=max_windows,
            max_components=args.factor_max_components,
            specs=specs,
        )
        write_candidate_factor_diagnostics_report(factor_diagnostics, output_dir)
        generated.extend(["candidate_factor_diagnostics.json", "candidate_factor_diagnostics.md"])

    regime_validation = None
    if args.include_regime_validation:
        regime_validation = run_candidate_regime_validation(
            provider,
            cfg,
            train_days=args.train_days,
            test_days=args.test_days,
            step_days=args.step_days,
            max_windows=max_windows,
            specs=specs,
            candidate_walk_forward=walk_forward,
        )
        write_candidate_regime_validation_report(regime_validation, output_dir)
        generated.extend(["candidate_regime_validation_report.json", "candidate_regime_validation_report.md"])

    goal = CapitalGoal(
        starting_capital=args.starting_capital,
        target_capital=args.target_capital,
        years=args.years,
        max_drawdown_budget=args.max_drawdown_budget,
    )
    selection_cfg, selection_scope, selection_start, selection_end = _selection_config(
        cfg,
        walk_forward.to_dict(),
        full_sample=args.full_sample_selection,
    )
    selection = run_candidate_selection(
        provider,
        selection_cfg,
        goal=goal,
        data_audit_status=str(_read_json(output_dir / "data_audit.json").get("status", "UNKNOWN")),
        robustness_status=str(_read_json(output_dir / "robustness_report.json").get("status", "UNKNOWN")),
        market_regime=(
            _read_json(output_dir / "market_regime.json")
            if selection_scope == "full_sample"
            else {}
        ),
        candidate_walk_forward=walk_forward.to_dict(),
        candidate_regime_validation=regime_validation.to_dict() if regime_validation else None,
        specs=specs,
    )
    write_candidate_selection_report(selection, output_dir)
    generated.extend(["candidate_selection.json", "candidate_selection.md", "candidate_selection.csv"])

    precheck = build_candidate_research_precheck_report(
        candidates=[spec.name for spec in specs],
        generated_artifacts=[
            *generated,
            "candidate_research_precheck.json",
            "candidate_research_precheck.md",
            "research_precheck_notice.json",
            "research_precheck_notice.md",
            "candidate_next_experiments.json",
            "candidate_next_experiments.md",
            "candidate_next_experiments.csv",
        ],
        candidate_selection=selection.to_dict(),
        candidate_walk_forward=walk_forward.to_dict(),
        factor_diagnostics=factor_diagnostics.to_dict() if factor_diagnostics else None,
        regime_validation=regime_validation.to_dict() if regime_validation else None,
        selection_scope=selection_scope,
        selection_start=selection_start,
        selection_end=selection_end,
    )
    write_candidate_research_precheck_report(precheck, output_dir)
    next_experiments = build_candidate_next_experiments_report(
        [
            CandidateReportBundle(
                report_dir=str(output_dir),
                candidate_selection=selection.to_dict(),
                candidate_research_precheck=precheck.to_dict(),
                candidate_walk_forward=walk_forward.to_dict(),
                factor_diagnostics=factor_diagnostics.to_dict() if factor_diagnostics else {},
                regime_validation=regime_validation.to_dict() if regime_validation else {},
            )
        ]
    )
    write_candidate_next_experiments_report(next_experiments, output_dir)

    logger.info("Research precheck status: {}", precheck.status)
    logger.info("Promotion decision: {}", precheck.promotion_decision)
    logger.info("Research top candidate: {}", precheck.research_top_candidate or "none")
    logger.info("Next research experiments: {}", next_experiments.experiment_count)
    logger.info("Research-only precheck written to {}", output_dir.resolve())


def _provider(cfg) -> DataProvider:
    storage = BarStorage(cfg.data.cache_path)
    provider = DataProvider(storage)
    if not provider.all_symbols() or not provider.trading_days(cfg.research.start, cfg.research.end):
        if not cfg.research.allow_demo_data:
            raise RuntimeError("No cached research data found and allow_demo_data=false.")
        seed_demo_data(storage, cfg.research.start, cfg.research.end)
    return provider


def _selection_config(
    cfg,
    walk_forward: dict,
    *,
    full_sample: bool,
):
    if full_sample:
        return cfg, "full_sample", str(cfg.research.start), str(cfg.research.end)
    windows = [
        row
        for row in walk_forward.get("windows", []) or []
        if isinstance(row, dict) and row.get("start") and row.get("end")
    ]
    latest = windows[-1] if windows else {}
    start = str(latest.get("start") or cfg.research.start)
    end = str(latest.get("end") or cfg.research.end)
    payload = cfg.to_dict()
    research = dict(payload.get("research", {}))
    research["start"] = start
    research["end"] = end
    if research.get("in_sample_end") and str(research["in_sample_end"]) >= end:
        research["in_sample_end"] = start
    if research.get("out_sample_start") and str(research["out_sample_start"]) > end:
        research["out_sample_start"] = start
    return type(cfg)({**payload, "research": research}), "latest_precheck_window", start, end


def _candidate_specs_or_exit(cfg, names: list[str] | None) -> list[CandidateSpec]:
    specs = candidate_specs_for_names(cfg, names)
    requested = {name for name in names or [] if name}
    found = {spec.name for spec in specs}
    missing = sorted(requested - found)
    if missing:
        available = ", ".join(spec.name for spec in candidate_specs_for_names(cfg, None))
        raise SystemExit(f"Unknown candidate(s): {', '.join(missing)}. Available: {available}")
    return specs


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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
