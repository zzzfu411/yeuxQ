"""Run a staged, research-only provider acquisition ramp.

Usage:
    uv run python examples/run_provider_acquisition_ramp.py --stage-sizes 2,20,100,300
"""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.provider_acquisition_ramp import (
    parse_stage_sizes,
    parse_symbols,
    run_provider_acquisition_ramp,
    write_provider_acquisition_ramp,
)
from quantify.utils.config import load_config

DEFAULT_RAMP_CACHE = Path("tmp/provider_acquisition_ramp.db")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run research-only provider acquisition ramp.")
    parser.add_argument("--config", default="config/research.yaml", help="YAML config path")
    parser.add_argument(
        "--cache",
        default=None,
        help=(
            "Ramp cache path. Defaults to tmp/provider_acquisition_ramp.db instead of "
            "the config cache so provider probes cannot silently promote the research cache."
        ),
    )
    parser.add_argument("--output-dir", default="results/provider_acquisition_ramp")
    parser.add_argument("--provider", default="akshare")
    parser.add_argument("--stage-sizes", default="2,20,100,300")
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbols. If set, skips provider all-A spot list requests.",
    )
    parser.add_argument("--include-st", action="store_true", help="Include ST symbols")
    args = parser.parse_args()

    cfg = load_config(args.config)
    cache_path = args.cache or DEFAULT_RAMP_CACHE
    stage_sizes = parse_stage_sizes(args.stage_sizes)
    symbols = parse_symbols(args.symbols)
    report = run_provider_acquisition_ramp(
        cache_path=cache_path,
        start=str(cfg.research.start),
        end=str(cfg.research.end),
        stage_sizes=stage_sizes,
        output_dir=args.output_dir,
        provider=args.provider,
        adjust=str(cfg.data.adjust),
        index_code=str(cfg.universe.index_code),
        include_st=args.include_st,
        symbols=symbols or None,
    )
    out = write_provider_acquisition_ramp(report, Path(args.output_dir))
    logger.info("Provider acquisition ramp status: {}", report.status)
    logger.info("Provider acquisition ramp report written to {}", out.resolve())
    logger.warning(
        "Provider ramp is research-only acquisition evidence; it is not source QA/provenance PASS."
    )
    if report.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
