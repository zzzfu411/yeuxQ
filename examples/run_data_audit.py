"""Run A-share daily data quality audit.

Usage:
    uv run python examples/run_data_audit.py --config config/research.yaml --output-dir results/audit/latest
"""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.audit import audit_data, write_data_audit
from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run A-share daily data quality audit.")
    parser.add_argument("--config", default="config/research.yaml", help="YAML config path")
    parser.add_argument("--cache", default=None, help="Override config data.cache_path")
    parser.add_argument("--output-dir", default=None, help="Output directory for data_audit files")
    args = parser.parse_args()
    cfg = load_config(args.config)
    cache_path = args.cache or cfg.data.cache_path
    provider = DataProvider(BarStorage(cache_path))
    report = audit_data(
        provider,
        cfg.research.start,
        cfg.research.end,
        data_source=cfg.data.source,
        cache_path=cache_path,
    )
    output_dir = Path(args.output_dir) if args.output_dir else Path(cfg.output.results_dir) / "data_audit"
    out = write_data_audit(report, output_dir)
    logger.info("Data audit status: {}", report.status)
    logger.info("Data audit written to {}", out.resolve())


if __name__ == "__main__":
    main()
