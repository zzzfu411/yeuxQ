"""Write a manual/external market context snapshot.

This command is offline and explicit: it records index-level context that a
human reviewed elsewhere. It does not download data, replace market_regime.json,
or approve any strategy gate.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.market import (
    MarketContextIndexMetric,
    build_market_context_snapshot,
    build_market_context_snapshot_from_csvs,
    write_market_context_snapshot,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Write auditable market context snapshot.")
    parser.add_argument("--output-dir", default="results/first_million")
    parser.add_argument("--as-of", required=True, help="Snapshot as-of date YYYY-MM-DD")
    parser.add_argument("--source", required=True, help="External source or manual evidence note")
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--reviewed-at", required=True, help="Review date YYYY-MM-DD")
    parser.add_argument(
        "--index",
        action="append",
        default=[],
        metavar="NAME,R20,R60,R120,MAX_DD,VOL[,BREADTH20,BREADTH60[,NOTE]]",
        help=(
            "Index metric row. Decimal returns are expected, e.g. "
            "CSI300,0.02,0.06,0.09,0.08,0.22,0.62,0.58,reviewed close."
        ),
    )
    parser.add_argument(
        "--index-csv",
        action="append",
        default=[],
        help=(
            "Optional local index daily CSV. Required columns: date and close. "
            "Long-form CSVs can include index/name/symbol/code. Can be supplied multiple times."
        ),
    )
    parser.add_argument("--encoding", default="utf-8-sig", help="CSV encoding, or auto")
    parser.add_argument("--breadth-note", default="")
    args = parser.parse_args()

    if args.index_csv:
        if args.index:
            raise SystemExit("--index and --index-csv cannot be combined; choose one evidence path.")
        snapshot = build_market_context_snapshot_from_csvs(
            csv_paths=args.index_csv,
            as_of=args.as_of,
            source=args.source,
            reviewed_by=args.reviewed_by,
            reviewed_at=args.reviewed_at,
            breadth_note=args.breadth_note,
            encoding=args.encoding,
        )
    else:
        snapshot = build_market_context_snapshot(
            as_of=args.as_of,
            source=args.source,
            reviewed_by=args.reviewed_by,
            reviewed_at=args.reviewed_at,
            index_metrics=[_parse_index(value) for value in args.index],
            breadth_note=args.breadth_note,
        )
    out = write_market_context_snapshot(snapshot, Path(args.output_dir))
    logger.info("Market context snapshot: {} ({})", snapshot.label, snapshot.status)
    logger.info("Market context snapshot written to {}", out.resolve())
    if snapshot.status == "BLOCK":
        raise SystemExit(2)


def _parse_index(value: str) -> MarketContextIndexMetric:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) < 6:
        return MarketContextIndexMetric(name=parts[0] if parts else "", note="Invalid --index row.")
    note = ",".join(parts[8:]).strip() if len(parts) > 8 else ""
    return MarketContextIndexMetric(
        name=parts[0],
        return_20d=_float_or_none(parts[1]),
        return_60d=_float_or_none(parts[2]),
        return_120d=_float_or_none(parts[3]),
        max_drawdown=_float_or_none(parts[4]),
        annualized_volatility=_float_or_none(parts[5]),
        breadth_above_ma20=_float_or_none(parts[6]) if len(parts) > 6 else None,
        breadth_above_ma60=_float_or_none(parts[7]) if len(parts) > 7 else None,
        note=note,
    )


def _float_or_none(value: str) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


if __name__ == "__main__":
    main()
