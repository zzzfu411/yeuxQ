"""Tests for storage + CSV feed (no network)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from quantify.data.csv_feed import CsvFeed
from quantify.data.storage import BarStorage


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["TEST", "TEST", "TEST"],
            "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "open": [100.0, 105.0, 110.0],
            "high": [108.0, 112.0, 115.0],
            "low": [99.0, 104.0, 108.0],
            "close": [105.0, 110.0, 112.0],
            "volume": [10000, 12000, 8000],
            "amount": [1_050_000.0, 1_320_000.0, 896_000.0],
        }
    )


def test_storage_roundtrip(tmp_path: Path, sample_df: pd.DataFrame) -> None:
    db = BarStorage(tmp_path / "q.db")
    db.save_bars(sample_df)
    out = db.load_bars("TEST")
    assert len(out) == 3
    assert list(out["date"]) == ["2024-01-02", "2024-01-03", "2024-01-04"]
    assert out["close"].iloc[-1] == pytest.approx(112.0)


def test_storage_upsert(tmp_path: Path, sample_df: pd.DataFrame) -> None:
    db = BarStorage(tmp_path / "q.db")
    db.save_bars(sample_df)

    # Replay with one row having different close → should overwrite, not duplicate
    mod = sample_df.copy()
    mod.loc[0, "close"] = 999.0
    db.save_bars(mod)

    out = db.load_bars("TEST")
    assert len(out) == 3  # no dupes thanks to PRIMARY KEY (symbol, date)
    assert out[out["date"] == "2024-01-02"]["close"].iloc[0] == pytest.approx(999.0)


def test_storage_date_range_filter(tmp_path: Path, sample_df: pd.DataFrame) -> None:
    db = BarStorage(tmp_path / "q.db")
    db.save_bars(sample_df)
    out = db.load_bars("TEST", start="2024-01-03", end="2024-01-03")
    assert len(out) == 1
    assert out["date"].iloc[0] == "2024-01-03"


def test_storage_last_date(tmp_path: Path, sample_df: pd.DataFrame) -> None:
    db = BarStorage(tmp_path / "q.db")
    assert db.last_date("TEST") is None
    db.save_bars(sample_df)
    assert db.last_date("TEST") == "2024-01-04"


def test_storage_iter_bars(tmp_path: Path, sample_df: pd.DataFrame) -> None:
    db = BarStorage(tmp_path / "q.db")
    db.save_bars(sample_df)
    bars = list(db.iter_bars("TEST"))
    assert len(bars) == 3
    assert bars[0].symbol == "TEST"
    assert bars[0].timestamp == datetime(2024, 1, 2)
    assert bars[-1].close == pytest.approx(112.0)


def test_csv_feed_stream(tmp_path: Path, sample_df: pd.DataFrame) -> None:
    csv_path = tmp_path / "test.csv"
    sample_df.to_csv(csv_path, index=False)
    feed = CsvFeed(csv_path)
    bars = list(feed.stream(["TEST"], "2024-01-02", "2024-01-04"))
    assert len(bars) == 3
    assert all(b.symbol == "TEST" for b in bars)
    assert bars[1].close == pytest.approx(110.0)
