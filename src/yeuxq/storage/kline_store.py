"""SQLite 日/周 K 线本地落盘。"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import List, Optional

from yeuxq.domain.models import Kline


class KlineStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS klines (
                        symbol TEXT NOT NULL,
                        period TEXT NOT NULL,
                        date TEXT NOT NULL,
                        open REAL, close REAL, high REAL, low REAL,
                        volume REAL, amount REAL, pct REAL, turnover REAL,
                        PRIMARY KEY (symbol, period, date)
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_kline_sym_period ON klines(symbol, period)"
                )
                conn.commit()
            finally:
                conn.close()

    def save_many(self, symbol: str, period: str, klines: List[Kline]) -> None:
        if not klines:
            return
        rows = [
            (
                symbol,
                period,
                k.date,
                k.open,
                k.close,
                k.high,
                k.low,
                k.volume,
                k.amount,
                k.pct,
                k.turnover,
            )
            for k in klines
        ]
        with self._lock:
            conn = self._connect()
            try:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO klines
                    (symbol, period, date, open, close, high, low, volume, amount, pct, turnover)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                conn.commit()
            finally:
                conn.close()

    def load(self, symbol: str, period: str, count: int) -> List[Kline]:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    """
                    SELECT date, open, close, high, low, volume, amount, pct, turnover
                    FROM klines
                    WHERE symbol=? AND period=?
                    ORDER BY date DESC
                    LIMIT ?
                    """,
                    (symbol, period, count),
                )
                rows = cur.fetchall()
            finally:
                conn.close()
        klines = [
            Kline(
                date=r["date"],
                open=r["open"] or 0,
                close=r["close"] or 0,
                high=r["high"] or 0,
                low=r["low"] or 0,
                volume=r["volume"] or 0,
                amount=r["amount"] or 0,
                pct=r["pct"] or 0,
                turnover=r["turnover"] or 0,
            )
            for r in reversed(rows)
        ]
        return klines

    def latest_date(self, symbol: str, period: str) -> Optional[str]:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "SELECT date FROM klines WHERE symbol=? AND period=? ORDER BY date DESC LIMIT 1",
                    (symbol, period),
                )
                row = cur.fetchone()
                return row["date"] if row else None
            finally:
                conn.close()
