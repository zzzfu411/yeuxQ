"""Canonical logical identity helpers for cached market bars.

The digest in this module identifies the normalized rows currently stored in
SQLite.  It is deliberately separate from a vendor/CSV dataset fingerprint:
the former detects cache mutation, while the latter identifies retained source
files and their validation evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Iterable, Sequence

LOGICAL_BAR_FINGERPRINT_ALGORITHM = "sha256:quantify.logical-bars.v1"
LOGICAL_BAR_FINGERPRINT_METADATA_KEY = "cache_logical_bar_fingerprint"
LOGICAL_BAR_FINGERPRINT_ALGORITHM_METADATA_KEY = "cache_logical_bar_fingerprint_algorithm"
PROSPECTIVE_PREFIX_FINGERPRINT_KEY = "prospective_prefix_logical_bar_fingerprint"
PROSPECTIVE_PREFIX_FINGERPRINT_END_KEY = "prospective_prefix_logical_bar_fingerprint_end"
PROSPECTIVE_PREFIX_FINGERPRINT_ALGORITHM_KEY = (
    "prospective_prefix_logical_bar_fingerprint_algorithm"
)
LATEST_IMPORT_BATCH_METADATA_KEY = "cache_latest_import_batch_id"
LINEAGE_SCHEMA_VERSION_METADATA_KEY = "cache_lineage_schema_version"
LINEAGE_SCHEMA_VERSION = "1"

BAR_COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume", "amount")


def canonical_bar_payload(row: Sequence[object]) -> bytes:
    """Return an unambiguous canonical byte representation for one bar row."""
    if len(row) != len(BAR_COLUMNS):
        raise ValueError(f"Expected {len(BAR_COLUMNS)} bar values, got {len(row)}")
    symbol = str(row[0])
    date_value = str(row[1])
    numeric = [_canonical_float(value) for value in row[2:]]
    payload = [symbol, date_value, *numeric]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def bar_row_fingerprint(row: Sequence[object]) -> str:
    """Hash one normalized bar row using the v1 canonical representation."""
    return hashlib.sha256(canonical_bar_payload(row)).hexdigest()


def logical_bar_fingerprint(rows: Iterable[Sequence[object]]) -> str:
    """Hash bars supplied in canonical ``(symbol, date)`` order."""
    digest = hashlib.sha256()
    digest.update(b"quantify.logical-bars.v1\n")
    count = 0
    for row in rows:
        payload = canonical_bar_payload(row)
        digest.update(len(payload).to_bytes(8, byteorder="big", signed=False))
        digest.update(payload)
        count += 1
    digest.update(count.to_bytes(8, byteorder="big", signed=False))
    return digest.hexdigest()


def logical_bar_fingerprint_from_connection(
    conn: sqlite3.Connection,
    *,
    end: str | None = None,
) -> str:
    """Compute the logical digest from SQLite, optionally through an inclusive cutoff."""
    if end is None:
        rows = conn.execute(
            """
            SELECT symbol, date, open, high, low, close, volume, amount
            FROM bars
            ORDER BY symbol COLLATE BINARY, date COLLATE BINARY
            """
        )
    else:
        rows = conn.execute(
            """
            SELECT symbol, date, open, high, low, close, volume, amount
            FROM bars
            WHERE date <= ?
            ORDER BY symbol COLLATE BINARY, date COLLATE BINARY
            """,
            (str(end),),
        )
    return logical_bar_fingerprint(rows)


def _canonical_float(value: object) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Bar numeric values must be finite, got {value!r}")
    # float.hex() is exact and independent of locale or decimal formatting.
    return number.hex()
