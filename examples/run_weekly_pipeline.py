"""Run the offline weekly research-to-paper evidence pipeline.

Usage:
    uv run python examples/run_weekly_pipeline.py --config config/research.yaml
"""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.ops import run_weekly_pipeline
from quantify.utils.config import Config, load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run weekly quant evidence pipeline.")
    parser.add_argument("--config", default="config/research.yaml", help="YAML config path")
    parser.add_argument("--cache", default=None, help="Optional override for data.cache_path")
    parser.add_argument("--output-dir", default=None, help="Optional fixed output directory")
    parser.add_argument("--starting-capital", type=float, default=100_000.0)
    parser.add_argument("--target-capital", type=float, default=1_000_000.0)
    parser.add_argument("--years", type=float, default=8.0)
    parser.add_argument("--max-drawdown-budget", type=float, default=0.20)
    parser.add_argument("--as-of", default=None, help="Real-data gate as-of date YYYY-MM-DD")
    parser.add_argument(
        "--wf-mode",
        choices=("expanding", "rolling"),
        default="expanding",
        help="Walk-forward training-window mode",
    )
    parser.add_argument("--wf-train-days", type=int, default=120, help="Walk-forward train days")
    parser.add_argument("--wf-purge-days", type=int, default=5, help="Gap after train")
    parser.add_argument("--wf-selection-days", type=int, default=20, help="Pre-test selection days")
    parser.add_argument("--wf-embargo-days", type=int, default=5, help="Gap before test")
    parser.add_argument("--wf-test-days", type=int, default=60, help="Walk-forward test-window days")
    parser.add_argument("--wf-step-days", type=int, default=60, help="Walk-forward step days")
    parser.add_argument(
        "--registry",
        default="results/strategy_registry/strategy_registry.json",
        help="Persistent strategy registry JSON path",
    )
    parser.add_argument(
        "--paper-state-dir",
        default=None,
        help="Optional continuous paper loop state directory for paper_stability review",
    )
    parser.add_argument("--no-registry", action="store_true", help="Do not update strategy registry")
    parser.add_argument(
        "--review-stage",
        default="paper",
        choices=["research", "paper", "micro_live_ready"],
        help="Deterministic review stage for llm_review artifacts. Micro-live preparation forces micro_live_ready.",
    )
    parser.add_argument(
        "--prepare-micro-live-readiness",
        action="store_true",
        help=(
            "Optionally generate manual target portfolio, manual_trade_sheet, "
            "risk_budget, and micro_live_readiness artifacts. This never creates "
            "approval records or broker orders."
        ),
    )
    parser.add_argument("--micro-live-candidate", default=None, help="Candidate for manual target planning")
    parser.add_argument("--micro-live-capital", type=float, default=None, help="Capital for manual target planning")
    parser.add_argument("--micro-live-cash-buffer-pct", type=float, default=0.05)
    parser.add_argument(
        "--current-positions",
        default=None,
        help="Optional current paper_positions.csv for manual target planning",
    )
    args = parser.parse_args()

    cfg = _load_config(args.config, cache_path=args.cache)
    result = run_weekly_pipeline(
        cfg,
        config_path=args.config,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        starting_capital=args.starting_capital,
        target_capital=args.target_capital,
        years=args.years,
        max_drawdown_budget=args.max_drawdown_budget,
        review_stage=args.review_stage,
        registry_path=None if args.no_registry else Path(args.registry),
        paper_state_dir=Path(args.paper_state_dir) if args.paper_state_dir else None,
        as_of=args.as_of,
        walk_forward_mode=args.wf_mode,
        walk_forward_train_days=args.wf_train_days,
        walk_forward_purge_days=args.wf_purge_days,
        walk_forward_selection_days=args.wf_selection_days,
        walk_forward_embargo_days=args.wf_embargo_days,
        walk_forward_test_days=args.wf_test_days,
        walk_forward_step_days=args.wf_step_days,
        prepare_micro_live_readiness=args.prepare_micro_live_readiness,
        micro_live_candidate=args.micro_live_candidate,
        micro_live_capital=args.micro_live_capital,
        micro_live_cash_buffer_pct=args.micro_live_cash_buffer_pct,
        current_positions_path=Path(args.current_positions) if args.current_positions else None,
    )
    logger.info("Weekly pipeline decision: {}", result.weekly_decision)
    logger.info("Weekly pipeline written to {}", Path(result.output_dir).resolve())

def _load_config(path: str, *, cache_path: str | None = None):
    if cache_path is None:
        return load_config(path)
    payload = load_config(path).to_dict()
    data = dict(payload.get("data", {}))
    data["cache_path"] = cache_path
    return Config({**payload, "data": data})


if __name__ == "__main__":
    main()
