"""Import real A-share research data into the local SQLite cache.

Usage:
    uv run python examples/import_research_data.py --config config/research.yaml --limit 300
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from loguru import logger

from quantify.data.research_importer import import_research_data, write_import_report
from quantify.data.storage import BarStorage
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Import real A-share research data via AKShare.")
    parser.add_argument("--config", default="config/research.yaml", help="YAML config path")
    parser.add_argument("--cache", default=None, help="Override config data.cache_path")
    parser.add_argument("--limit", type=int, default=300, help="Max symbols to import")
    parser.add_argument("--output-dir", default="results/import", help="Output directory")
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbols. If set, skips the all-A spot list request.",
    )
    parser.add_argument(
        "--symbols-file",
        default=None,
        help=(
            "Optional text/CSV file of symbols. If set, skips the all-A spot list request. "
            "Supports comma, whitespace, newline, or a CSV first column named symbol/code."
        ),
    )
    parser.add_argument("--include-st", action="store_true", help="Include ST symbols")
    parser.add_argument("--include-bj", action="store_true", help="Include Beijing Stock Exchange symbols")
    args = parser.parse_args()

    cfg = load_config(args.config)
    cache_path = args.cache or cfg.data.cache_path
    symbols = _read_symbols(args.symbols, args.symbols_file)
    storage = BarStorage(cache_path)
    report = import_research_data(
        storage,
        cfg.research.start,
        cfg.research.end,
        limit=args.limit,
        adjust=cfg.data.adjust,
        index_code=cfg.universe.index_code,
        include_st=args.include_st,
        include_bj=args.include_bj,
        symbols=symbols or None,
    )
    out = write_import_report(report, Path(args.output_dir))
    logger.info("Research data import status: {}", report.status)
    logger.info("Research data import report written to {}", out.resolve())
    if report.status == "BLOCK":
        logger.error("Research data import blocked. See {}", (out / "data_import.md").resolve())
        raise SystemExit(2)

def _read_symbols(symbols_arg: str, symbols_file: str | None) -> list[str]:
    values = []
    values.extend(_split_symbols(symbols_arg))
    if symbols_file:
        values.extend(_read_symbols_file(Path(symbols_file)))
    return _dedupe_symbols(values)


def _read_symbols_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        rows = list(csv.DictReader(text.splitlines()))
        if rows:
            fields = [field for field in (rows[0].keys() if rows else []) if field]
            symbol_field = next(
                (field for field in fields if field.strip().lower() in {"symbol", "code", "ticker"}),
                fields[0] if fields else "",
            )
            return [str(row.get(symbol_field, "")).strip() for row in rows]
    return _split_symbols(text)


def _split_symbols(text: str) -> list[str]:
    cleaned = text.replace(",", " ").replace(";", " ")
    return [item.strip() for item in cleaned.split() if item.strip()]


def _dedupe_symbols(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        symbol = value.strip()
        if not symbol:
            continue
        if symbol not in seen:
            result.append(symbol)
            seen.add(symbol)
    return result


if __name__ == "__main__":
    main()
