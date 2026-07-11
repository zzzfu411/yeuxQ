from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from examples.import_research_data import _read_symbols
from quantify.data.provider import DataProvider
from quantify.data.research_importer import fetch_a_share_spot_info, import_research_data, write_import_report
from quantify.data.storage import BarStorage


def test_fetch_a_share_spot_info_normalizes_and_filters_st_and_bj() -> None:
    raw = pd.DataFrame(
        {
            "代码": ["600001", "000001", "430001", "300001"],
            "名称": ["正常沪", "ST深", "北交所", "正常创"],
        }
    )

    with patch("akshare.stock_zh_a_spot_em", return_value=raw):
        info = fetch_a_share_spot_info(include_st=False, include_bj=False)

    assert info["symbol"].tolist() == ["300001", "600001"]
    assert set(info["exchange"]) == {"SZSE", "SSE"}
    assert info["is_st"].sum() == 0


def test_import_research_data_writes_real_cache_and_report(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "research.db")
    raw_info = pd.DataFrame({"代码": ["600001", "000001"], "名称": ["正常沪", "正常深"]})
    bars = pd.DataFrame(
        {
            "symbol": ["600001", "600001"],
            "date": ["2024-01-02", "2024-01-03"],
            "open": [10.0, 10.2],
            "high": [10.5, 10.6],
            "low": [9.9, 10.1],
            "close": [10.2, 10.4],
            "volume": [1000, 1200],
            "amount": [10_200, 12_480],
        }
    )

    def fake_fetch(self, symbol, start, end):
        frame = bars.assign(symbol=symbol)
        self.storage.save_bars(frame)
        return frame

    with (
        patch("akshare.stock_zh_a_spot_em", return_value=raw_info),
        patch("quantify.data.akshare_feed.AkshareFeed.fetch", fake_fetch),
    ):
        report = import_research_data(storage, "2024-01-02", "2024-01-03", limit=2)

    out = write_import_report(report, tmp_path / "import")
    provider = DataProvider(storage)
    assert report.status == "PASS"
    assert report.imported_symbols == 2
    assert report.metadata["actual_bar_start"] == "2024-01-02"
    assert report.metadata["actual_bar_end"] == "2024-01-03"
    assert report.metadata["actual_bar_symbol_count"] == 2
    assert report.network_blocked is False
    assert report.failure_stage == ""
    assert "real_data_bootstrap" in report.next_actions[0]
    assert provider.all_symbols() == ["000001", "600001"]
    assert provider.trading_days("2024-01-02", "2024-01-03") == ["2024-01-02", "2024-01-03"]
    assert (out / "data_import.json").exists()


def test_import_research_data_blocks_when_all_symbols_fail(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "research.db")
    raw_info = pd.DataFrame({"代码": ["600001"], "名称": ["正常沪"]})

    def fail_fetch(self, symbol, start, end):
        raise RuntimeError("network down")

    with (
        patch("akshare.stock_zh_a_spot_em", return_value=raw_info),
        patch("quantify.data.akshare_feed.AkshareFeed.fetch", fail_fetch),
    ):
        report = import_research_data(storage, "2024-01-02", "2024-01-03", limit=1)

    out = write_import_report(report, tmp_path / "import")
    payload = json.loads((out / "data_import.json").read_text(encoding="utf-8"))
    markdown = (out / "data_import.md").read_text(encoding="utf-8")

    assert report.status == "BLOCK"
    assert report.imported_symbols == 0
    assert report.failed_symbols == 1
    assert report.bar_rows == 0
    assert "network down" in report.failures[0].reason
    assert report.failure_stage == "bars"
    assert report.recommended_route == "retry_provider_or_offline_csv"
    assert any("offline" in action.lower() for action in report.next_actions)
    assert not any("Data imported from AKShare" in note for note in report.notes)
    assert any("No usable AKShare bars" in note for note in report.notes)
    assert payload["status"] == "BLOCK"
    assert payload["imported_symbols"] == 0
    assert payload["bar_rows"] == 0
    assert payload["metadata"]["actual_bar_start"] == ""
    assert payload["metadata"]["actual_bar_end"] == ""
    assert "Data imported from AKShare and stored as real research cache." not in markdown
    assert "No usable AKShare bars were imported" in markdown


def test_import_research_data_blocks_empty_bars_without_success_note(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "research.db")
    raw_info = pd.DataFrame({"symbol": ["600001"], "name": ["normal"]})

    def empty_fetch(self, symbol, start, end):
        return pd.DataFrame()

    with (
        patch("akshare.stock_zh_a_spot_em", return_value=raw_info),
        patch("quantify.data.akshare_feed.AkshareFeed.fetch", empty_fetch),
    ):
        report = import_research_data(storage, "2024-01-02", "2024-01-03", limit=1)

    assert report.status == "BLOCK"
    assert report.imported_symbols == 0
    assert report.bar_rows == 0
    assert report.failures[0].reason == "empty bars"
    assert not any("stored as real research cache" in note for note in report.notes)
    assert any("No usable AKShare bars" in note for note in report.notes)


def test_import_research_data_blocks_when_symbol_list_provider_fails(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "research.db")
    with patch("akshare.stock_zh_a_spot_em", side_effect=RuntimeError("provider down")):
        report = import_research_data(storage, "2024-01-02", "2024-01-03")

    assert report.status == "BLOCK"
    assert report.failures[0].symbol == "symbol_list"
    assert "provider down" in report.failures[0].reason
    assert report.failure_stage == "symbol_list"
    assert report.metadata["failure_stage"] == "symbol_list"
    assert report.metadata["network_blocked"] is False


def test_import_research_data_classifies_network_blocked_symbol_list(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "research.db")
    with patch(
        "akshare.stock_zh_a_spot_em",
        side_effect=ConnectionError("Max retries exceeded: Unable to connect to proxy"),
    ):
        report = import_research_data(storage, "2024-01-02", "2024-01-03")

    assert report.status == "BLOCK"
    assert report.failure_stage == "symbol_list"
    assert report.network_blocked is True
    assert report.metadata["network_blocked"] is True
    assert report.recommended_route == "offline_csv_or_tdx"
    assert "guarded offline CSV/TDX" in report.next_actions[0]


def test_import_research_data_can_skip_spot_list_with_manual_symbols(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "research.db")
    bars = pd.DataFrame(
        {
            "symbol": ["600001"],
            "date": ["2024-01-02"],
            "open": [10.0],
            "high": [10.5],
            "low": [9.9],
            "close": [10.2],
            "volume": [1000],
            "amount": [10_200],
        }
    )

    def fake_fetch(self, symbol, start, end):
        frame = bars.assign(symbol=symbol)
        self.storage.save_bars(frame)
        return frame

    with patch("quantify.data.akshare_feed.AkshareFeed.fetch", fake_fetch):
        report = import_research_data(
            storage,
            "2024-01-02",
            "2024-01-03",
            symbols=["600001"],
        )

    assert report.status == "PASS"
    assert report.metadata["actual_bar_end"] == "2024-01-02"
    assert DataProvider(storage).all_symbols() == ["600001"]


def test_import_research_data_cli_reads_symbol_file(tmp_path: Path) -> None:
    symbols_file = tmp_path / "symbols.csv"
    symbols_file.write_text(
        "\n".join(
            [
                "symbol,name",
                "600001,alpha",
                "000001,beta",
                "600001,duplicate",
            ]
        ),
        encoding="utf-8",
    )

    symbols = _read_symbols("300001, 002001", str(symbols_file))

    assert symbols == ["300001", "002001", "600001", "000001"]
