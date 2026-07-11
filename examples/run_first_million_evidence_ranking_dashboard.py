"""Build the first-million evidence-to-ranking dashboard."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.ops.first_million_evidence_ranking_dashboard import (
    build_first_million_evidence_ranking_dashboard,
    write_first_million_evidence_ranking_dashboard,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build first-million evidence-to-ranking dashboard."
    )
    parser.add_argument("--report-dir", default="results/first_million")
    parser.add_argument("--data-dir", default="data_exports")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--as-of", default=None, help="Evidence as-of date YYYY-MM-DD")
    args = parser.parse_args()

    dashboard = build_first_million_evidence_ranking_dashboard(
        report_dir=args.report_dir,
        data_dir=args.data_dir,
        as_of=args.as_of,
    )
    out = write_first_million_evidence_ranking_dashboard(
        dashboard,
        Path(args.output_dir or args.report_dir),
    )
    logger.info("First-million evidence ranking dashboard decision: {}", dashboard.decision)
    logger.info("First-million evidence ranking dashboard written to {}", out.resolve())
    if dashboard.decision == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
