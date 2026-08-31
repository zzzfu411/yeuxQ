"""Render a research report directory as a self-contained HTML dashboard.

Usage:
    uv run python examples/build_report_dashboard.py \
        --report-dir results/research/<timestamp>
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import webbrowser

from loguru import logger

from quantify.analytics.dashboard import DashboardInputError, write_dashboard


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a zero-dependency, self-contained HTML dashboard for a research report."
    )
    parser.add_argument(
        "--report-dir",
        required=True,
        type=Path,
        help="Directory containing summary.json and optional report evidence files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output HTML path (default: <report-dir>/dashboard.html).",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Optional dashboard title; otherwise summary.json/title or the directory name is used.",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        dest="open_browser",
        help="Open the generated dashboard in the default browser.",
    )
    args = parser.parse_args(argv)

    try:
        output = write_dashboard(args.report_dir, args.output, title=args.title)
    except (DashboardInputError, OSError) as exc:
        logger.error("Could not build dashboard: {}", exc)
        return 2

    logger.info("Dashboard written to {}", output.resolve())
    if args.open_browser:
        opened = webbrowser.open(output.resolve().as_uri())
        if not opened:
            logger.warning("The default browser did not accept the dashboard URL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
