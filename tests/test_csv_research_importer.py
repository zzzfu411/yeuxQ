from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.csv_research_importer import import_research_csvs
from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage


def test_import_research_csvs_loads_bars_metadata_and_fundamentals(tmp_path: Path) -> None:
    bars_csv = tmp_path / "bars.csv"
    stock_csv = tmp_path / "stock.csv"
    fundamentals_csv = tmp_path / "fundamentals.csv"
    calendar_csv = tmp_path / "calendar.csv"
    suspensions_csv = tmp_path / "suspensions.csv"
    index_csv = tmp_path / "index_constituents.csv"
    _bars().to_csv(bars_csv, index=False)
    pd.DataFrame({"symbol": ["600001", "000001"], "name": ["A", "B"], "industry": ["x", "y"]}).to_csv(
        stock_csv,
        index=False,
    )
    pd.DataFrame(
        {
            "symbol": ["600001", "000001"],
            "date": ["2024-01-03", "2024-01-03"],
            "pe_ttm": [10.0, 12.0],
            "roe": [0.1, 0.12],
        }
    ).to_csv(fundamentals_csv, index=False)
    pd.DataFrame({"date": ["2024-01-02", "2024-01-03"], "is_open": [1, 1]}).to_csv(
        calendar_csv,
        index=False,
    )
    pd.DataFrame({"symbol": ["000001"], "date": ["2024-01-03"], "is_suspended": [1]}).to_csv(
        suspensions_csv,
        index=False,
    )
    pd.DataFrame(
        {
            "index_code": ["000906", "000906"],
            "date": ["2024-01-02", "2024-01-02"],
            "symbol": ["600001", "000001"],
        }
    ).to_csv(index_csv, index=False)
    storage = BarStorage(tmp_path / "research.db")

    report = import_research_csvs(
        storage,
        bars_csv=bars_csv,
        stock_info_csv=stock_csv,
        fundamentals_csv=fundamentals_csv,
        calendar_csv=calendar_csv,
        suspensions_csv=suspensions_csv,
        index_constituents_csv=index_csv,
    )

    provider = DataProvider(storage)
    assert report.status == "PASS"
    assert report.imported_symbols == 2
    assert report.metadata["actual_bar_start"] == "2024-01-02"
    assert report.metadata["actual_bar_end"] == "2024-01-03"
    assert report.metadata["actual_bar_symbol_count"] == 2
    assert provider.trading_days("2024-01-02", "2024-01-03") == ["2024-01-02", "2024-01-03"]
    assert set(provider.all_symbols()) == {"000001", "600001"}
    assert not provider.fundamentals(["000001", "600001"], "2024-01-03").empty
    assert provider.suspended_symbols("2024-01-03") == {"000001"}
    assert provider.index_constituents("000906", "2024-01-03") == ["000001", "600001"]


def test_import_research_csvs_blocks_missing_bars_file(tmp_path: Path) -> None:
    report = import_research_csvs(BarStorage(tmp_path / "research.db"), bars_csv=tmp_path / "missing.csv")

    assert report.status == "BLOCK"
    assert report.failures[0].symbol == "bars_csv"


def test_import_research_csvs_accepts_broker_style_chinese_export(tmp_path: Path) -> None:
    bars_csv = tmp_path / "bars.csv"
    suspensions_csv = tmp_path / "suspensions.csv"
    index_csv = tmp_path / "index_constituents.csv"
    _broker_style_bars().to_csv(bars_csv, index=False)
    pd.DataFrame({"证券代码": ["SZ000001"], "交易日期": [20240103], "是否停牌": [1]}).to_csv(
        suspensions_csv,
        index=False,
    )
    pd.DataFrame(
        {
            "指数代码": ["SH000906", "SH000906"],
            "交易日期": [20240102, 20240102],
            "证券代码": ["600001.SH", "000001.SZ"],
        }
    ).to_csv(index_csv, index=False)
    storage = BarStorage(tmp_path / "research.db")

    report = import_research_csvs(
        storage,
        bars_csv=bars_csv,
        suspensions_csv=suspensions_csv,
        index_constituents_csv=index_csv,
    )

    provider = DataProvider(storage)
    assert report.status == "PASS"
    assert set(provider.all_symbols()) == {"000001", "600001"}
    assert provider.suspended_symbols("2024-01-03") == {"000001"}
    assert provider.index_constituents("000906", "2024-01-03") == ["000001", "600001"]


def test_import_research_csvs_accepts_gbk_chinese_export(tmp_path: Path) -> None:
    bars_csv = tmp_path / "bars.csv"
    stock_csv = tmp_path / "stock_info.csv"
    calendar_csv = tmp_path / "calendar.csv"
    _broker_style_bars().to_csv(bars_csv, index=False, encoding="gbk")
    pd.DataFrame(
        {
            "证券代码": ["600001.SH", "000001.SZ"],
            "证券简称": ["样本A", "样本B"],
            "行业": ["工业", "金融"],
            "是否ST": [0, 0],
        }
    ).to_csv(stock_csv, index=False, encoding="gbk")
    pd.DataFrame({"交易日期": [20240102, 20240103], "是否开市": [1, 1]}).to_csv(
        calendar_csv,
        index=False,
        encoding="gbk",
    )
    storage = BarStorage(tmp_path / "research.db")

    report = import_research_csvs(
        storage,
        bars_csv=bars_csv,
        stock_info_csv=stock_csv,
        calendar_csv=calendar_csv,
        encoding="gbk",
    )

    provider = DataProvider(storage)
    assert report.status == "PASS"
    assert set(provider.all_symbols()) == {"000001", "600001"}
    assert provider.trading_days("2024-01-02", "2024-01-03") == ["2024-01-02", "2024-01-03"]


def test_import_research_csv_cli_accepts_normal_chinese_export(tmp_path: Path) -> None:
    bars_csv = tmp_path / "bars.csv"
    stock_csv = tmp_path / "stock_info.csv"
    fundamentals_csv = tmp_path / "fundamentals.csv"
    calendar_csv = tmp_path / "calendar.csv"
    suspensions_csv = tmp_path / "suspensions.csv"
    index_csv = tmp_path / "index_constituents.csv"
    _normal_chinese_bars().to_csv(bars_csv, index=False)
    pd.DataFrame(
        {
            "证券代码": ["600001.SH", "000001.SZ"],
            "证券简称": ["样本A", "样本B"],
            "交易所": ["SSE", "SZSE"],
            "上市日期": ["2001-01-01", "2002-01-01"],
            "退市日期": ["", ""],
            "行业": ["工业", "金融"],
            "是否ST": ["否", "否"],
        }
    ).to_csv(stock_csv, index=False)
    pd.DataFrame(
        {
            "股票代码": ["600001.SH", "000001.SZ"],
            "交易日期": [20240102, 20240102],
            "市盈率TTM": [10.0, 12.0],
            "市净率": [1.0, 1.1],
            "净资产收益率": [0.10, 0.12],
            "总市值": [10_000_000_000, 12_000_000_000],
            "换手率": [0.01, 0.02],
        }
    ).to_csv(fundamentals_csv, index=False)
    pd.DataFrame({"交易日期": [20240102, 20240103], "是否开市": ["是", "是"]}).to_csv(
        calendar_csv,
        index=False,
    )
    pd.DataFrame({"证券代码": ["000001.SZ"], "交易日期": [20240103], "是否停牌": ["是"]}).to_csv(
        suspensions_csv,
        index=False,
    )
    pd.DataFrame(
        {
            "指数代码": ["000906.SH", "000906.SH"],
            "交易日期": [20240102, 20240102],
            "证券代码": ["600001.SH", "000001.SZ"],
        }
    ).to_csv(index_csv, index=False)
    cache = tmp_path / "research.db"
    output = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/import_research_csv.py",
            "--cache",
            str(cache),
            "--bars-csv",
            str(bars_csv),
            "--stock-info-csv",
            str(stock_csv),
            "--fundamentals-csv",
            str(fundamentals_csv),
            "--calendar-csv",
            str(calendar_csv),
            "--suspensions-csv",
            str(suspensions_csv),
            "--index-constituents-csv",
            str(index_csv),
            "--validate",
            "--start",
            "2024-01-02",
            "--end",
            "2024-01-03",
            "--min-symbols",
            "2",
            "--output-dir",
            str(output),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output / "data_import.json").read_text(encoding="utf-8"))
    validation = json.loads((output / "csv_validation.json").read_text(encoding="utf-8"))
    provider = DataProvider(BarStorage(cache))
    assert completed.returncode == 0
    assert payload["status"] == "PASS"
    assert validation["status"] == "PASS"
    assert set(provider.all_symbols()) == {"000001", "600001"}
    assert provider.suspended_symbols("2024-01-03") == {"000001"}
    assert provider.index_constituents("000906", "2024-01-03") == ["000001", "600001"]


def test_import_research_csv_cli_writes_report(tmp_path: Path) -> None:
    bars_csv = tmp_path / "bars.csv"
    _bars().to_csv(bars_csv, index=False)
    cache = tmp_path / "research.db"
    output = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/import_research_csv.py",
            "--cache",
            str(cache),
            "--bars-csv",
            str(bars_csv),
            "--output-dir",
            str(output),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    report = json.loads((output / "data_import.json").read_text(encoding="utf-8"))
    assert report["status"] == "PASS"


def test_import_research_csv_cli_validate_writes_data_version_metadata(tmp_path: Path) -> None:
    bars_csv = tmp_path / "bars.csv"
    stock_csv = tmp_path / "stock.csv"
    calendar_csv = tmp_path / "calendar.csv"
    suspensions_csv = tmp_path / "suspensions.csv"
    index_csv = tmp_path / "index_constituents.csv"
    _bars().to_csv(bars_csv, index=False)
    pd.DataFrame({"symbol": ["600001", "000001"], "name": ["A", "B"]}).to_csv(
        stock_csv,
        index=False,
    )
    pd.DataFrame({"date": ["2024-01-02", "2024-01-03"], "is_open": [1, 1]}).to_csv(
        calendar_csv,
        index=False,
    )
    pd.DataFrame({"symbol": ["000001"], "date": ["2024-01-03"], "is_suspended": [1]}).to_csv(
        suspensions_csv,
        index=False,
    )
    pd.DataFrame({"index_code": ["000906"], "date": ["2024-01-02"], "symbol": ["000001"]}).to_csv(
        index_csv,
        index=False,
    )
    cache = tmp_path / "research.db"
    output = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/import_research_csv.py",
            "--cache",
            str(cache),
            "--bars-csv",
            str(bars_csv),
            "--stock-info-csv",
            str(stock_csv),
            "--calendar-csv",
            str(calendar_csv),
            "--suspensions-csv",
            str(suspensions_csv),
            "--index-constituents-csv",
            str(index_csv),
            "--validate",
            "--start",
            "2024-01-02",
            "--end",
            "2024-01-03",
            "--min-symbols",
            "2",
            "--output-dir",
            str(output),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    validation = json.loads((output / "csv_validation.json").read_text(encoding="utf-8"))
    report = json.loads((output / "data_import.json").read_text(encoding="utf-8"))
    assert validation["dataset_fingerprint"]
    assert report["metadata"]["csv_validation_status"] == "WATCH"
    assert report["metadata"]["csv_dataset_fingerprint"] == validation["dataset_fingerprint"]
    metadata = BarStorage(cache).load_metadata()
    assert metadata["csv_dataset_fingerprint"] == validation["dataset_fingerprint"]
    assert metadata["last_import_source"] == "local_csv"


def test_import_research_csv_cli_auto_detects_encoding_for_validation_and_import(tmp_path: Path) -> None:
    bars_csv = tmp_path / "bars.csv"
    stock_csv = tmp_path / "stock_info.csv"
    calendar_csv = tmp_path / "calendar.csv"
    _broker_style_bars().to_csv(bars_csv, index=False, encoding="gbk")
    pd.DataFrame({"证券代码": ["600001.SH", "000001.SZ"], "证券简称": ["样本A", "样本B"]}).to_csv(
        stock_csv,
        index=False,
        encoding="gbk",
    )
    pd.DataFrame({"交易日期": [20240102, 20240103], "是否开市": [1, 1]}).to_csv(
        calendar_csv,
        index=False,
        encoding="gbk",
    )
    cache = tmp_path / "research.db"
    output = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/import_research_csv.py",
            "--cache",
            str(cache),
            "--bars-csv",
            str(bars_csv),
            "--stock-info-csv",
            str(stock_csv),
            "--calendar-csv",
            str(calendar_csv),
            "--validate",
            "--start",
            "2024-01-02",
            "--end",
            "2024-01-03",
            "--min-symbols",
            "2",
            "--encoding",
            "auto",
            "--output-dir",
            str(output),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output / "data_import.json").read_text(encoding="utf-8"))
    provider = DataProvider(BarStorage(cache))
    assert completed.returncode == 0
    assert payload["status"] == "WATCH"
    assert set(provider.all_symbols()) == {"000001", "600001"}


def test_import_research_csv_cli_validate_blocks_before_cache_write(tmp_path: Path) -> None:
    bars_csv = tmp_path / "bars.csv"
    _bars().drop(columns=["close"]).to_csv(bars_csv, index=False)
    cache = tmp_path / "research.db"
    output = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/import_research_csv.py",
            "--cache",
            str(cache),
            "--bars-csv",
            str(bars_csv),
            "--validate",
            "--output-dir",
            str(output),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    validation = json.loads((output / "csv_validation.json").read_text(encoding="utf-8"))
    assert validation["status"] == "BLOCK"
    assert not cache.exists()


def _bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["600001", "600001", "000001", "000001"],
            "date": ["2024-01-02", "2024-01-03", "2024-01-02", "2024-01-03"],
            "open": [10.0, 10.1, 20.0, 20.1],
            "high": [10.5, 10.6, 20.5, 20.6],
            "low": [9.8, 10.0, 19.8, 20.0],
            "close": [10.2, 10.3, 20.2, 20.3],
            "volume": [1000, 1100, 2000, 2100],
            "amount": [10_200, 11_330, 40_400, 42_630],
        }
    )


def _broker_style_bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "证券代码": ["600001.SH", "600001.SH", "SZ000001", "SZ000001"],
            "交易日期": [20240102, 20240103, 20240102, 20240103],
            "开盘价": [10.0, 10.1, 20.0, 20.1],
            "最高价": [10.5, 10.6, 20.5, 20.6],
            "最低价": [9.8, 10.0, 19.8, 20.0],
            "收盘价": [10.2, 10.3, 20.2, 20.3],
            "成交量": [1000, 1100, 2000, 2100],
            "成交额": [10_200, 11_330, 40_400, 42_630],
        }
    )


def _normal_chinese_bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "证券代码": ["600001.SH", "600001.SH", "SZ000001", "SZ000001"],
            "交易日期": [20240102, 20240103, 20240102, 20240103],
            "开盘价": [10.0, 10.1, 20.0, 20.1],
            "最高价": [10.5, 10.6, 20.5, 20.6],
            "最低价": [9.8, 10.0, 19.8, 20.0],
            "收盘价": [10.2, 10.3, 20.2, 20.3],
            "成交量": [1000, 1100, 2000, 2100],
            "成交额": [10_200, 11_330, 40_400, 42_630],
        }
    )
