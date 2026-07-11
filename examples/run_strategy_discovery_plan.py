"""Build the first-million strategy discovery plan."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.ops.strategy_discovery_plan import (
    build_strategy_discovery_plan,
    write_strategy_discovery_plan,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build first-million strategy discovery plan.")
    parser.add_argument("--report-dir", default="results/first_million")
    parser.add_argument("--config", default="config/research_recent.yaml")
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    args = parser.parse_args()

    plan = build_strategy_discovery_plan(
        args.report_dir,
        as_of=args.as_of,
        config_path=args.config,
    )
    out = write_strategy_discovery_plan(plan, Path(args.report_dir))
    logger.info("Strategy discovery plan decision: {}", plan.decision)
    logger.info("Strategy discovery plan written to {}", out.resolve())
    if plan.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
