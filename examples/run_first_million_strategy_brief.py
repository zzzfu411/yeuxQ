"""Write a first-million strategy brief from current evidence artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from loguru import logger

from quantify.ops.strategy_brief import (
    build_first_million_strategy_brief,
    write_first_million_strategy_brief,
)
from quantify.research.candidate_experiment_readiness import (
    build_candidate_experiment_readiness_from_report,
)
from quantify.research.candidate_hypotheses import build_candidate_hypothesis_catalog
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Write first-million strategy brief.")
    parser.add_argument("--report-dir", default="results/first_million")
    parser.add_argument("--config", default="config/research_recent.yaml")
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args()

    root = Path(args.report_dir)
    cfg = load_config(args.config)
    readiness = build_candidate_experiment_readiness_from_report(root, as_of=args.as_of)
    catalog = build_candidate_hypothesis_catalog(cfg, as_of=args.as_of)
    brief = build_first_million_strategy_brief(
        readiness=readiness,
        hypothesis_catalog=catalog,
        data_gap_plan=_read_json(root / "data_gap_action_plan.json"),
        data_evidence_packet=_read_json(root / "data_evidence_action_packet.json"),
        offline_package=_read_json(root / "offline_data_package.json"),
        market_regime=_read_first_available_json(
            root / "market_regime.json",
            root / "weekly" / "market_regime.json",
        ),
        market_context_snapshot=_read_json(root / "market_context_snapshot.json"),
        capital_goal_status=_read_first_available_json(
            root / "goal" / "capital_goal_status.json",
            root / "weekly" / "capital_goal_status.json",
        ),
        compounding_path_review=_read_json(root / "goal" / "compounding_path_review.json"),
        candidate_selection=_read_first_available_json(
            root / "candidate_selection.json",
            root / "weekly" / "candidate_selection.json",
        ),
        as_of=args.as_of,
    )
    out = write_first_million_strategy_brief(brief, root)
    logger.info("First-million strategy brief decision: {}", brief.decision)
    logger.info("First-million strategy brief written to {}", out.resolve())


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_first_available_json(*paths: Path) -> dict[str, Any]:
    for path in paths:
        payload = _read_json(path)
        if payload:
            return payload
    return {}


if __name__ == "__main__":
    main()
