"""Run a research-only candidate stress matrix without promotion rights.

This command intentionally does not accept --gate-report-dir and does not call
the guarded launch gate. It is for non-promotional research triage only.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.research.candidate_stress_matrix import (
    run_candidate_stress_matrix,
    select_candidate_stress_scenarios,
    write_candidate_stress_matrix_report,
)
from quantify.research.candidates import candidate_specs_for_names
from quantify.research.demo_data import seed_demo_data
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run research-only candidate stress matrix."
    )
    parser.add_argument("--config", default="config/research.yaml", help="YAML config path")
    parser.add_argument("--cache", default=None, help="Override config data.cache_path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--candidate", action="append", default=None, help="Restrict to a candidate name")
    parser.add_argument("--research-start", default=None, help="Override config research.start")
    parser.add_argument("--research-end", default=None, help="Override config research.end")
    parser.add_argument(
        "--scenario",
        action="append",
        default=None,
        help="Restrict to a named stress scenario. Can be passed more than once.",
    )
    args = parser.parse_args()

    cfg = _load_config(
        args.config,
        cache_path=args.cache,
        research_start=args.research_start,
        research_end=args.research_end,
    )
    storage = BarStorage(cfg.data.cache_path)
    provider = DataProvider(storage)
    if not provider.all_symbols() or not provider.trading_days(cfg.research.start, cfg.research.end):
        if not cfg.research.allow_demo_data:
            raise RuntimeError("No cached research data found and allow_demo_data=false.")
        seed_demo_data(storage, cfg.research.start, cfg.research.end)

    specs = candidate_specs_for_names(cfg, args.candidate)
    scenarios_by_candidate = {
        spec.name: select_candidate_stress_scenarios(spec, args.scenario) for spec in specs
    }
    report = run_candidate_stress_matrix(
        provider,
        cfg,
        specs=specs,
        scenarios_by_candidate=scenarios_by_candidate,
    )
    out = write_candidate_stress_matrix_report(report, Path(args.output_dir))
    logger.info("Research stress matrix status: {}", report.status)
    logger.info("Promotion decision: {}", report.promotion_decision)
    logger.info("Stress status: {}", report.stress_status)
    logger.info("Research-only stress matrix written to {}", out.resolve())


def _load_config(
    path: str,
    *,
    cache_path: str | None = None,
    research_start: str | None = None,
    research_end: str | None = None,
):
    cfg = load_config(path)
    if cache_path is None and research_start is None and research_end is None:
        return cfg
    payload = cfg.to_dict()
    data = dict(payload.get("data", {}))
    if cache_path is not None:
        data["cache_path"] = cache_path
    research = dict(payload.get("research", {}))
    if research_start is not None:
        research["start"] = research_start
    if research_end is not None:
        research["end"] = research_end
    return type(cfg)({**payload, "data": data, "research": research})


if __name__ == "__main__":
    main()
