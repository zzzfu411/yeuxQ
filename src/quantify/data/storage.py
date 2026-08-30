"""SQLite-backed bar storage.

Single-file SQLite database (default ./data_cache/quotes.db) holds OHLCV history.
Why SQLite over Parquet/CSV:
    - Indexed lookup by (symbol, date range) is fast without loading the whole file.
    - Single file is easy to back up / git-ignore.
    - Standard library only, no extra dependencies.

Schema:
    bars(symbol TEXT, date TEXT (ISO 'YYYY-MM-DD'),
         open REAL, high REAL, low REAL, close REAL, volume REAL, amount REAL,
         PRIMARY KEY (symbol, date))
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from quantify.core.bar import Bar
from quantify.data.provenance import (
    LATEST_IMPORT_BATCH_METADATA_KEY,
    LINEAGE_SCHEMA_VERSION,
    LINEAGE_SCHEMA_VERSION_METADATA_KEY,
    LOGICAL_BAR_FINGERPRINT_ALGORITHM,
    LOGICAL_BAR_FINGERPRINT_ALGORITHM_METADATA_KEY,
    LOGICAL_BAR_FINGERPRINT_METADATA_KEY,
    bar_row_fingerprint,
    logical_bar_fingerprint_from_connection,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    symbol TEXT NOT NULL,
    date   TEXT NOT NULL,
    open   REAL NOT NULL,
    high   REAL NOT NULL,
    low    REAL NOT NULL,
    close  REAL NOT NULL,
    volume REAL NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_bars_symbol_date ON bars(symbol, date);

CREATE TABLE IF NOT EXISTS stock_info (
    symbol TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    exchange TEXT NOT NULL DEFAULT '',
    list_date TEXT NOT NULL DEFAULT '',
    delist_date TEXT NOT NULL DEFAULT '',
    industry TEXT NOT NULL DEFAULT '',
    is_st INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trading_calendar (
    date TEXT PRIMARY KEY,
    is_open INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS suspensions (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    is_suspended INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS index_constituents (
    index_code TEXT NOT NULL,
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    PRIMARY KEY (index_code, date, symbol)
);

CREATE TABLE IF NOT EXISTS fundamentals (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    pe_ttm REAL,
    pb REAL,
    roe REAL,
    market_cap REAL,
    turnover_rate REAL,
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_fundamentals_symbol_date ON fundamentals(symbol, date);

CREATE TABLE IF NOT EXISTS research_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_import_batches (
    batch_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    source_type TEXT NOT NULL,
    source_reference TEXT NOT NULL DEFAULT '',
    source_fingerprint_kind TEXT NOT NULL DEFAULT '',
    source_fingerprint TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    started_at_utc TEXT NOT NULL,
    committed_at_utc TEXT NOT NULL,
    input_row_count INTEGER NOT NULL,
    written_row_count INTEGER NOT NULL,
    distinct_symbol_count INTEGER NOT NULL,
    bar_start TEXT NOT NULL,
    bar_end TEXT NOT NULL,
    pre_import_logical_fingerprint TEXT NOT NULL,
    post_import_logical_fingerprint TEXT NOT NULL,
    logical_fingerprint_algorithm TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS bar_import_lineage (
    lineage_id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    row_fingerprint TEXT NOT NULL,
    recorded_at_utc TEXT NOT NULL,
    UNIQUE(batch_id, symbol, date),
    FOREIGN KEY(batch_id) REFERENCES data_import_batches(batch_id)
);
CREATE INDEX IF NOT EXISTS idx_bar_import_lineage_bar
    ON bar_import_lineage(symbol, date, lineage_id);
CREATE INDEX IF NOT EXISTS idx_bar_import_lineage_batch
    ON bar_import_lineage(batch_id);
"""


@dataclass(frozen=True, slots=True)
class BarImportAttestation:
    """Committed identity of one atomic bar import batch."""

    batch_id: str
    source_type: str
    source_reference: str
    source_fingerprint_kind: str
    source_fingerprint: str
    committed_at_utc: str
    input_row_count: int
    written_row_count: int
    distinct_symbol_count: int
    bar_start: str
    bar_end: str
    pre_import_logical_fingerprint: str
    post_import_logical_fingerprint: str
    logical_fingerprint_algorithm: str = LOGICAL_BAR_FINGERPRINT_ALGORITHM

    def to_dict(self) -> dict[str, object]:
        return {
            "batch_id": self.batch_id,
            "source_type": self.source_type,
            "source_reference": self.source_reference,
            "source_fingerprint_kind": self.source_fingerprint_kind,
            "source_fingerprint": self.source_fingerprint,
            "committed_at_utc": self.committed_at_utc,
            "input_row_count": self.input_row_count,
            "written_row_count": self.written_row_count,
            "distinct_symbol_count": self.distinct_symbol_count,
            "bar_start": self.bar_start,
            "bar_end": self.bar_end,
            "pre_import_logical_fingerprint": self.pre_import_logical_fingerprint,
            "post_import_logical_fingerprint": self.post_import_logical_fingerprint,
            "logical_fingerprint_algorithm": self.logical_fingerprint_algorithm,
        }


class BarStorage:
    """Thin SQLite wrapper for OHLCV bar persistence."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(_SCHEMA)

    # ----- write -----
    def save_bars(self, df: pd.DataFrame) -> int:
        """Upsert bars from a DataFrame.

        Expected columns: symbol, date (str ISO), open, high, low, close, volume, amount.
        Returns number of rows written.
        """
        required = {"symbol", "date", "open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"save_bars: missing columns {missing}")

        if "amount" not in df.columns:
            df = df.assign(amount=0.0)

        rows = df[["symbol", "date", "open", "high", "low", "close", "volume", "amount"]].itertuples(
            index=False, name=None
        )
        with sqlite3.connect(self.db_path) as conn:
            # INSERT OR REPLACE = upsert on PRIMARY KEY (symbol, date)
            conn.executemany(
                """
                INSERT INTO bars (symbol, date, open, high, low, close, volume, amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, date) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    amount = excluded.amount
                """,
                rows,
            )
            return conn.total_changes

    def save_bars_with_lineage(
        self,
        df: pd.DataFrame,
        *,
        source_type: str,
        source_reference: str = "",
        source_fingerprint_kind: str = "",
        source_fingerprint: str = "",
        source_metadata: dict[str, Any] | None = None,
        cache_metadata: dict[str, object] | None = None,
        batch_id: str | None = None,
        imported_at_utc: str | None = None,
    ) -> BarImportAttestation:
        """Atomically upsert bars, lineage, batch identity, and cache digest."""
        rows = _normalized_bar_rows(df)
        if not rows:
            raise ValueError("save_bars_with_lineage requires at least one bar row")
        keys = [(row[0], row[1]) for row in rows]
        if len(keys) != len(set(keys)):
            raise ValueError("save_bars_with_lineage received duplicate (symbol, date) rows")
        source_type = str(source_type).strip()
        if not source_type:
            raise ValueError("save_bars_with_lineage requires a non-empty source_type")

        resolved_batch_id = str(batch_id or uuid4())
        committed_at = imported_at_utc or datetime.now(UTC).replace(microsecond=0).isoformat()
        symbols = {row[0] for row in rows}
        dates = [row[1] for row in rows]
        metadata_json = json.dumps(
            source_metadata or {},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN IMMEDIATE")
            pre_fingerprint = logical_bar_fingerprint_from_connection(conn)
            conn.execute(
                """
                INSERT INTO data_import_batches (
                    batch_id, schema_version, source_type, source_reference,
                    source_fingerprint_kind, source_fingerprint, status,
                    started_at_utc, committed_at_utc, input_row_count,
                    written_row_count, distinct_symbol_count, bar_start, bar_end,
                    pre_import_logical_fingerprint, post_import_logical_fingerprint,
                    logical_fingerprint_algorithm, metadata_json
                ) VALUES (?, 1, ?, ?, ?, ?, 'IN_PROGRESS', ?, '', ?, 0, ?, ?, ?, ?, '', ?, ?)
                """,
                (
                    resolved_batch_id,
                    source_type,
                    str(source_reference),
                    str(source_fingerprint_kind),
                    str(source_fingerprint),
                    committed_at,
                    len(rows),
                    len(symbols),
                    min(dates),
                    max(dates),
                    pre_fingerprint,
                    LOGICAL_BAR_FINGERPRINT_ALGORITHM,
                    metadata_json,
                ),
            )
            conn.executemany(
                "INSERT OR REPLACE INTO bars VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            lineage_rows = [
                (
                    resolved_batch_id,
                    row[0],
                    row[1],
                    bar_row_fingerprint(row),
                    committed_at,
                )
                for row in rows
            ]
            conn.executemany(
                """
                INSERT INTO bar_import_lineage (
                    batch_id, symbol, date, row_fingerprint, recorded_at_utc
                ) VALUES (?, ?, ?, ?, ?)
                """,
                lineage_rows,
            )
            post_fingerprint = logical_bar_fingerprint_from_connection(conn)
            conn.execute(
                """
                UPDATE data_import_batches
                SET status = 'COMMITTED', committed_at_utc = ?, written_row_count = ?,
                    post_import_logical_fingerprint = ?
                WHERE batch_id = ?
                """,
                (committed_at, len(rows), post_fingerprint, resolved_batch_id),
            )
            attestation_metadata: dict[str, object] = {
                **(cache_metadata or {}),
                LOGICAL_BAR_FINGERPRINT_METADATA_KEY: post_fingerprint,
                LOGICAL_BAR_FINGERPRINT_ALGORITHM_METADATA_KEY: LOGICAL_BAR_FINGERPRINT_ALGORITHM,
                LATEST_IMPORT_BATCH_METADATA_KEY: resolved_batch_id,
                LINEAGE_SCHEMA_VERSION_METADATA_KEY: LINEAGE_SCHEMA_VERSION,
            }
            conn.executemany(
                "INSERT OR REPLACE INTO research_metadata(key, value) VALUES (?, ?)",
                [(str(key), str(value)) for key, value in attestation_metadata.items()],
            )

        return BarImportAttestation(
            batch_id=resolved_batch_id,
            source_type=source_type,
            source_reference=str(source_reference),
            source_fingerprint_kind=str(source_fingerprint_kind),
            source_fingerprint=str(source_fingerprint),
            committed_at_utc=committed_at,
            input_row_count=len(rows),
            written_row_count=len(rows),
            distinct_symbol_count=len(symbols),
            bar_start=min(dates),
            bar_end=max(dates),
            pre_import_logical_fingerprint=pre_fingerprint,
            post_import_logical_fingerprint=post_fingerprint,
        )

    def logical_bar_fingerprint(self, *, end: str | None = None) -> str:
        """Return the v1 logical digest, optionally through an inclusive date cutoff."""
        with sqlite3.connect(self.db_path) as conn:
            return logical_bar_fingerprint_from_connection(conn, end=end)

    def load_import_batches(self) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query(
                "SELECT * FROM data_import_batches ORDER BY rowid",
                conn,
            )

    def load_bar_lineage(self, batch_id: str | None = None) -> pd.DataFrame:
        sql = "SELECT * FROM bar_import_lineage"
        params: list[object] = []
        if batch_id is not None:
            sql += " WHERE batch_id = ?"
            params.append(batch_id)
        sql += " ORDER BY lineage_id"
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query(sql, conn, params=params)

    def save_stock_info(self, df: pd.DataFrame) -> int:
        required = {"symbol"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"save_stock_info: missing columns {missing}")
        normalized = df.copy()
        defaults = {
            "name": "",
            "exchange": "",
            "list_date": "",
            "delist_date": "",
            "industry": "",
            "is_st": 0,
        }
        for col, default in defaults.items():
            if col not in normalized.columns:
                normalized[col] = default
        rows = normalized[
            ["symbol", "name", "exchange", "list_date", "delist_date", "industry", "is_st"]
        ].itertuples(index=False, name=None)
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO stock_info VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            return conn.total_changes

    def save_calendar(self, dates: list[str] | pd.Series | pd.DatetimeIndex) -> int:
        rows = [(_iso(pd.Timestamp(d).date()) if not isinstance(d, str) else d, 1) for d in dates]
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO trading_calendar(date, is_open) VALUES (?, ?)",
                rows,
            )
            return conn.total_changes

    def save_suspensions(self, df: pd.DataFrame) -> int:
        required = {"symbol", "date"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"save_suspensions: missing columns {missing}")
        normalized = df.copy()
        if "is_suspended" not in normalized.columns:
            normalized["is_suspended"] = 1
        rows = normalized[["symbol", "date", "is_suspended"]].itertuples(index=False, name=None)
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO suspensions VALUES (?, ?, ?)",
                rows,
            )
            return conn.total_changes

    def save_index_constituents(self, index_code: str, date_value: str, symbols: list[str]) -> int:
        rows = [(index_code, date_value, sym) for sym in symbols]
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO index_constituents VALUES (?, ?, ?)",
                rows,
            )
            return conn.total_changes

    def save_fundamentals(self, df: pd.DataFrame) -> int:
        required = {"symbol", "date"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"save_fundamentals: missing columns {missing}")
        normalized = df.copy()
        for col in ("pe_ttm", "pb", "roe", "market_cap", "turnover_rate"):
            if col not in normalized.columns:
                normalized[col] = None
        rows = normalized[
            ["symbol", "date", "pe_ttm", "pb", "roe", "market_cap", "turnover_rate"]
        ].itertuples(index=False, name=None)
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO fundamentals VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            return conn.total_changes

    def save_metadata(self, metadata: dict[str, object]) -> int:
        rows = [(str(key), str(value)) for key, value in metadata.items()]
        if not rows:
            return 0
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO research_metadata(key, value) VALUES (?, ?)",
                rows,
            )
            return conn.total_changes

    # ----- read -----
    def load_bars(
        self,
        symbol: str,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> pd.DataFrame:
        """Load bars for one symbol, optionally between [start, end] (inclusive)."""
        sql = "SELECT * FROM bars WHERE symbol = ?"
        params: list = [symbol]
        if start is not None:
            sql += " AND date >= ?"
            params.append(_iso(start))
        if end is not None:
            sql += " AND date <= ?"
            params.append(_iso(end))
        sql += " ORDER BY date ASC"

        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query(sql, conn, params=params)
        return df

    def load_all_bars(
        self,
        symbols: list[str],
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> pd.DataFrame:
        if not symbols:
            return pd.DataFrame(
                columns=["symbol", "date", "open", "high", "low", "close", "volume", "amount"]
            )
        placeholders = ",".join("?" for _ in symbols)
        sql = f"SELECT * FROM bars WHERE symbol IN ({placeholders})"
        params: list = list(symbols)
        if start is not None:
            sql += " AND date >= ?"
            params.append(_iso(start))
        if end is not None:
            sql += " AND date <= ?"
            params.append(_iso(end))
        sql += " ORDER BY date ASC, symbol ASC"
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query(sql, conn, params=params)

    def load_stock_info(self) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query("SELECT * FROM stock_info ORDER BY symbol", conn)

    def load_all_bars_from_db_symbols(self) -> list[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT DISTINCT symbol FROM bars ORDER BY symbol").fetchall()
        return [row[0] for row in rows]

    def load_calendar(
        self,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> list[str]:
        sql = "SELECT date FROM trading_calendar WHERE is_open = 1"
        params: list = []
        if start is not None:
            sql += " AND date >= ?"
            params.append(_iso(start))
        if end is not None:
            sql += " AND date <= ?"
            params.append(_iso(end))
        sql += " ORDER BY date ASC"
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [row[0] for row in rows]

    def load_index_constituents(self, index_code: str, as_of: str | date) -> list[str]:
        as_of_iso = _iso(as_of)
        with sqlite3.connect(self.db_path) as conn:
            date_row = conn.execute(
                "SELECT MAX(date) FROM index_constituents WHERE index_code = ? AND date <= ?",
                (index_code, as_of_iso),
            ).fetchone()
            if not date_row or date_row[0] is None:
                return []
            rows = conn.execute(
                """
                SELECT symbol FROM index_constituents
                WHERE index_code = ? AND date = ?
                ORDER BY symbol
                """,
                (index_code, date_row[0]),
            ).fetchall()
        return [row[0] for row in rows]

    def load_fundamentals(
        self,
        symbols: list[str],
        as_of: str | date,
    ) -> pd.DataFrame:
        if not symbols:
            return pd.DataFrame(
                columns=["symbol", "date", "pe_ttm", "pb", "roe", "market_cap", "turnover_rate"]
            )
        as_of_iso = _iso(as_of)
        placeholders = ",".join("?" for _ in symbols)
        sql = f"""
            SELECT f.*
            FROM fundamentals f
            JOIN (
                SELECT symbol, MAX(date) AS date
                FROM fundamentals
                WHERE symbol IN ({placeholders}) AND date <= ?
                GROUP BY symbol
            ) latest
            ON f.symbol = latest.symbol AND f.date = latest.date
            ORDER BY f.symbol
        """
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query(sql, conn, params=[*symbols, as_of_iso])

    def load_suspended_symbols(self, as_of: str | date) -> set[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT symbol FROM suspensions WHERE date = ? AND is_suspended = 1",
                (_iso(as_of),),
            ).fetchall()
        return {row[0] for row in rows}

    def load_metadata(self) -> dict[str, str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT key, value FROM research_metadata ORDER BY key").fetchall()
        return {row[0]: row[1] for row in rows}

    def iter_bars(
        self,
        symbol: str,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> Iterator[Bar]:
        """Iterate bars as Bar dataclasses, chronologically."""
        df = self.load_bars(symbol, start, end)
        for row in df.itertuples(index=False):
            yield Bar(
                symbol=row.symbol,
                timestamp=datetime.fromisoformat(row.date),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
                amount=float(row.amount),
            )

    def last_date(self, symbol: str) -> str | None:
        """Most recent date stored for a symbol (ISO 'YYYY-MM-DD'), or None."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT MAX(date) FROM bars WHERE symbol = ?", (symbol,)
            ).fetchone()
        return row[0] if row and row[0] else None


def _iso(d: str | date) -> str:
    if isinstance(d, str):
        return d
    return d.isoformat()


def _normalized_bar_rows(df: pd.DataFrame) -> list[tuple[str, str, float, float, float, float, float, float]]:
    required = {"symbol", "date", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"save_bars_with_lineage: missing columns {missing}")
    normalized = df if "amount" in df.columns else df.assign(amount=0.0)
    rows: list[tuple[str, str, float, float, float, float, float, float]] = []
    columns = ["symbol", "date", "open", "high", "low", "close", "volume", "amount"]
    for values in normalized[columns].itertuples(index=False, name=None):
        symbol = str(values[0]).strip()
        date_value = str(values[1]).strip()
        if not symbol:
            raise ValueError("save_bars_with_lineage requires non-empty symbols")
        try:
            parsed_date = date.fromisoformat(date_value)
        except ValueError as exc:
            raise ValueError(
                f"save_bars_with_lineage requires ISO dates, got {date_value!r}"
            ) from exc
        if parsed_date.isoformat() != date_value:
            raise ValueError(f"save_bars_with_lineage requires ISO dates, got {date_value!r}")
        row = (
            symbol,
            date_value,
            float(values[2]),
            float(values[3]),
            float(values[4]),
            float(values[5]),
            float(values[6]),
            float(values[7]),
        )
        # Canonicalization performs finite-value validation before any transaction writes.
        bar_row_fingerprint(row)
        rows.append(row)
    return rows
