from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from quantify.data.akshare_feed import AkshareFeed
from quantify.data.storage import BarStorage


def test_akshare_feed_uses_eastmoney_when_primary_succeeds(tmp_path: Path) -> None:
    feed = AkshareFeed(BarStorage(tmp_path / "bars.db"), adjust="qfq")

    with (
        patch("quantify.data.akshare_feed.ak.stock_zh_a_hist", return_value=_primary_frame()),
        patch("quantify.data.akshare_feed.ak.stock_zh_a_daily") as fallback,
    ):
        bars = feed.fetch("000001", "2026-07-13", "2026-07-14")

    assert len(bars) == 2
    assert feed.fetch_routes == {"000001": "eastmoney"}
    assert bars["volume"].tolist() == [100_000.0, 110_000.0]
    fallback.assert_not_called()


def test_akshare_feed_falls_back_to_sina_and_normalizes_bars(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "bars.db")
    feed = AkshareFeed(storage, adjust="qfq")

    with (
        patch(
            "quantify.data.akshare_feed.ak.stock_zh_a_hist",
            side_effect=ConnectionError("eastmoney disconnected"),
        ),
        patch(
            "quantify.data.akshare_feed.ak.stock_zh_a_daily",
            return_value=_sina_frame(),
        ) as fallback,
    ):
        bars = feed.fetch("000001", "2026-07-13", "2026-07-14")

    fallback.assert_called_once_with(
        symbol="sz000001",
        start_date="20260713",
        end_date="20260714",
        adjust="qfq",
    )
    assert feed.fetch_routes == {"000001": "sina"}
    assert bars["volume"].tolist() == [1000, 1100]
    assert list(bars.columns) == [
        "symbol",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]
    assert storage.last_date("000001") == "2026-07-14"


def test_akshare_feed_reports_both_provider_failures(tmp_path: Path) -> None:
    feed = AkshareFeed(BarStorage(tmp_path / "bars.db"), adjust="qfq")

    with (
        patch(
            "quantify.data.akshare_feed.ak.stock_zh_a_hist",
            side_effect=ConnectionError("eastmoney disconnected"),
        ),
        patch(
            "quantify.data.akshare_feed.ak.stock_zh_a_daily",
            side_effect=TimeoutError("sina timeout"),
        ),
        pytest.raises(RuntimeError, match="Eastmoney failed.*Sina failed"),
    ):
        feed.fetch("600000", "2026-07-13", "2026-07-14")

    assert feed.fetch_routes == {}


def test_nonpersistent_feed_fetches_without_any_storage_handle() -> None:
    feed = AkshareFeed(None, adjust="qfq", persist=False)

    with (
        patch("quantify.data.akshare_feed.ak.stock_zh_a_hist", return_value=_primary_frame()),
        patch("quantify.data.akshare_feed.ak.stock_zh_a_daily") as fallback,
    ):
        bars = feed.fetch("000001", "2026-07-13", "2026-07-14")

    assert len(bars) == 2
    assert feed.storage is None
    assert feed.fetch_routes == {"000001": "eastmoney"}
    fallback.assert_not_called()


def test_storage_is_required_for_persistence_and_cache_operations() -> None:
    with pytest.raises(ValueError, match="storage is required"):
        AkshareFeed(None, persist=True)

    feed = AkshareFeed(None, persist=False)
    with pytest.raises(RuntimeError, match="BarStorage"):
        feed.ensure_cached("000001", "2026-07-13", "2026-07-14")


def _primary_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2026-07-13", "2026-07-14"],
            "open": [10.0, 10.1],
            "high": [10.2, 10.3],
            "low": [9.9, 10.0],
            "close": [10.1, 10.2],
            "volume": [1000, 1100],
            "amount": [10_100, 11_220],
        }
    )


def _sina_frame() -> pd.DataFrame:
    frame = _primary_frame()
    frame["outstanding_share"] = [1_000_000, 1_000_000]
    frame["turnover"] = [0.001, 0.0011]
    return frame
