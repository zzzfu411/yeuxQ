"""Run multi-factor robustness experiments.

Usage:
    uv run python examples/run_robustness.py --config config/research.yaml --output-dir results/research/<timestamp>
"""
from __future__ import annotations

import argparse

from loguru import logger

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.research.demo_data import seed_demo_data
from quantify.research.robustness import default_scenarios, run_robustness, write_robustness_report
from quantify.utils.config import Config, load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run robustness experiments.")
    parser.add_argument("--config", default="config/research.yaml", help="YAML config path")
    parser.add_argument("--cache", default=None, help="Override config data.cache_path")
    parser.add_argument("--output-dir", required=True, help="Directory for robustness_report files")
    parser.add_argument(
        "--scenario",
        action="append",
        default=None,
        help="Run only the named scenario. Can be passed more than once. Defaults to all scenarios.",
    )
    parser.add_argument("--mode", choices=("expanding", "rolling"), default="expanding")
    parser.add_argument("--train-days", type=int, default=120)
    parser.add_argument("--purge-days", type=int, default=5)
    parser.add_argument("--selection-days", type=int, default=20)
    parser.add_argument("--embargo-days", type=int, default=5)
    parser.add_argument("--test-days", type=int, default=60)
    parser.add_argument("--step-days", type=int, default=60)
    args = parser.parse_args()
    cfg = _load_config(args.config, cache_path=args.cache)
    storage = BarStorage(cfg.data.cache_path)
    provider = DataProvider(storage)
    if not provider.all_symbols() or not provider.trading_days(cfg.research.start, cfg.research.end):
        if not cfg.research.allow_demo_data:
            raise RuntimeError("No cached research data found and allow_demo_data=false.")
        seed_demo_data(storage, cfg.research.start, cfg.research.end)
    scenarios = _select_scenarios(cfg, args.scenario)
    logger.info("Running robustness scenarios: {}", ", ".join(scenario.name for scenario in scenarios))
    report = run_robustness(
        provider,
        cfg,
        scenarios,
        mode=args.mode,
        train_days=args.train_days,
        purge_days=args.purge_days,
        selection_days=args.selection_days,
        embargo_days=args.embargo_days,
        test_days=args.test_days,
        step_days=args.step_days,
    )
    out = write_robustness_report(report, args.output_dir)
    logger.info("Robustness status: {}", report.status)
    logger.info("Robustness report written to {}", out.resolve())


def _select_scenarios(cfg: Config, names: list[str] | None):
    scenarios = default_scenarios(cfg)
    if not names:
        return scenarios
    wanted = {name.strip() for name in names if name.strip()}
    selected = [scenario for scenario in scenarios if scenario.name in wanted]
    missing = sorted(wanted - {scenario.name for scenario in scenarios})
    if missing:
        raise ValueError(f"Unknown robustness scenario(s): {', '.join(missing)}")
    if not selected:
        raise ValueError("No robustness scenarios selected.")
    return selected


def _load_config(path: str, *, cache_path: str | None = None) -> Config:
    cfg = load_config(path)
    if cache_path is None:
        return cfg
    payload = cfg.to_dict()
    data = dict(payload.get("data", {}))
    data["cache_path"] = cache_path
    return Config({**payload, "data": data})


if __name__ == "__main__":
    main()
