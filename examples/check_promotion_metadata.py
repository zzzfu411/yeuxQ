"""Check promotion-facing cache metadata without mutating the cache."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.cache_metadata import (
    build_promotion_metadata_check,
    write_promotion_metadata_check,
)
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Check cache metadata required for promotion gates.")
    parser.add_argument("--config", default=None, help="Optional YAML config with data.cache_path")
    parser.add_argument("--cache", default=None, help="Optional SQLite cache path; overrides --config")
    parser.add_argument("--output-dir", default="results/import/promotion_metadata")
    parser.add_argument(
        "--require-evidence-manifest",
        action="store_true",
        help="Require source QA evidence manifest metadata in addition to checklist and answers hashes.",
    )
    args = parser.parse_args()

    if args.cache:
        cache_path = Path(args.cache)
    elif args.config:
        cfg = load_config(args.config)
        cache_path = Path(str(cfg.data.cache_path))
    else:
        parser.error("Provide --cache or --config.")

    check = build_promotion_metadata_check(
        cache_path,
        require_evidence_manifest=args.require_evidence_manifest,
    )
    out = write_promotion_metadata_check(check, Path(args.output_dir))
    logger.info("Promotion metadata check status: {}", check.status)
    logger.info("Promotion metadata check written to {}", out.resolve())
    if check.status == "BLOCK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
