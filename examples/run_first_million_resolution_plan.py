"""Build a resolution queue from a first-million pipeline report directory."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.ops.first_million_resolution import (
    build_first_million_resolution_plan,
    write_first_million_resolution_plan,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build first-million blocker resolution plan.")
    parser.add_argument("--report-dir", default="results/first_million")
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    args = parser.parse_args()

    plan = build_first_million_resolution_plan(args.report_dir, as_of=args.as_of)
    out = write_first_million_resolution_plan(plan, Path(args.report_dir))
    logger.info("First-million resolution plan decision: {}", plan.decision)
    logger.info("First-million resolution plan written to {}", out.resolve())
    if plan.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
