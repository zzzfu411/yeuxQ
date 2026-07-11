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

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

import pandas as pd

from quantify.core.bar import Bar

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
"""


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
                "INSERT OR REPLACE INTO bars VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            return conn.total_changes

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
