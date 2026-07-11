from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.csv_contract import (
    validate_research_csvs,
    write_csv_validation_report,
    write_research_csv_templates,
)


def test_write_research_csv_templates_creates_schema_files(tmp_path: Path) -> None:
    paths = write_research_csv_templates(tmp_path)

    assert {path.name for path in paths} == {
        "bars.csv",
        "stock_info.csv",
        "fundamentals.csv",
        "calendar.csv",
        "suspensions.csv",
        "index_constituents.csv",
        "README.md",
    }
    assert "symbol" in (tmp_path / "bars.csv").read_text(encoding="utf-8").splitlines()[0]


def test_validate_research_csvs_passes_complete_small_export(tmp_path: Path) -> None:
    write_research_csv_templates(tmp_path)

    report = validate_research_csvs(
        bars_csv=tmp_path / "bars.csv",
        stock_info_csv=tmp_path / "stock_info.csv",
        fundamentals_csv=tmp_path / "fundamentals.csv",
        calendar_csv=tmp_path / "calendar.csv",
        suspensions_csv=tmp_path / "suspensions.csv",
        index_constituents_csv=tmp_path / "index_constituents.csv",
        start="2024-01-02",
        end="2024-01-03",
        min_symbols=2,
    )
    out = write_csv_validation_report(report, tmp_path / "out")

    assert report.status == "PASS"
    assert report.dataset_fingerprint
    assert report.metrics["bars_symbol_count"] == 2
    assert all(file.sha256 for file in report.files if file.exists)
    assert (out / "csv_validation.json").exists()


def test_validate_research_csvs_blocks_invalid_ohlc(tmp_path: Path) -> None:
    bars = _bars()
    bars.loc[0, "high"] = 9.0
    bars.to_csv(tmp_path / "bars.csv", index=False)

    report = validate_research_csvs(
        bars_csv=tmp_path / "bars.csv",
        start="2024-01-02",
        end="2024-01-03",
        min_symbols=2,
    )

    assert report.status == "BLOCK"
    assert any(finding.code == "BARS_INVALID_OHLC" for finding in report.findings)


def test_validate_research_csvs_blocks_stale_bars_even_when_schema_valid(tmp_path: Path) -> None:
    _bars().to_csv(tmp_path / "bars.csv", index=False)

    report = validate_research_csvs(
        bars_csv=tmp_path / "bars.csv",
        start="2024-01-02",
        end="2024-02-20",
        min_symbols=2,
        max_end_lag_days=10,
    )

    assert report.status == "BLOCK"
    finding = next(finding for finding in report.findings if finding.code == "BARS_END_BEFORE_EXPECTED")
    assert finding.severity == "BLOCK"
    assert finding.evidence["lag_days"] == 48
    assert report.metrics["bars_end_lag_days"] == 48


def test_validate_research_csvs_accepts_broker_style_chinese_export(tmp_path: Path) -> None:
    _broker_style_bars().to_csv(tmp_path / "bars.csv", index=False)
    pd.DataFrame(
        {
            "证券代码": ["600001.SH", "SZ000001"],
            "证券简称": ["样本A", "样本B"],
            "行业": ["工业", "金融"],
            "是否ST": [0, 0],
        }
    ).to_csv(tmp_path / "stock_info.csv", index=False)
    pd.DataFrame(
        {
            "股票代码": ["600001.SH", "000001.SZ"],
            "交易日期": [20240102, 20240102],
            "市盈率TTM": [10.0, 12.0],
            "市净率": [1.0, 1.1],
        }
    ).to_csv(tmp_path / "fundamentals.csv", index=False)
    pd.DataFrame({"交易日期": [20240102, 20240103], "是否开市": [1, 1]}).to_csv(
        tmp_path / "calendar.csv",
        index=False,
    )
    pd.DataFrame({"证券代码": ["000001.SZ"], "交易日期": [20240103], "是否停牌": [1]}).to_csv(
        tmp_path / "suspensions.csv",
        index=False,
    )
    pd.DataFrame(
        {
            "指数代码": ["SH000906", "SH000906"],
            "交易日期": [20240102, 20240102],
            "证券代码": ["600001.SH", "000001.SZ"],
        }
    ).to_csv(tmp_path / "index_constituents.csv", index=False)

    report = validate_research_csvs(
        bars_csv=tmp_path / "bars.csv",
        stock_info_csv=tmp_path / "stock_info.csv",
        fundamentals_csv=tmp_path / "fundamentals.csv",
        calendar_csv=tmp_path / "calendar.csv",
        suspensions_csv=tmp_path / "suspensions.csv",
        index_constituents_csv=tmp_path / "index_constituents.csv",
        start="2024-01-02",
        end="2024-01-03",
        min_symbols=2,
    )

    assert report.status == "PASS"
    assert report.metrics["bars_symbol_count"] == 2
    assert report.metrics["suspended_symbol_day_count"] == 1
    assert report.metrics["index_constituent_symbol_count"] == 2


def test_validate_research_csvs_auto_detects_gbk_export(tmp_path: Path) -> None:
    _normal_chinese_bars().to_csv(tmp_path / "bars.csv", index=False, encoding="gbk")

    report = validate_research_csvs(
        bars_csv=tmp_path / "bars.csv",
        start="2024-01-02",
        end="2024-01-03",
        min_symbols=2,
        encoding="auto",
    )

    assert report.status in {"PASS", "WATCH"}
    assert report.metrics["bars_symbol_count"] == 2


def test_validate_research_csv_cli_writes_outputs(tmp_path: Path) -> None:
    write_research_csv_templates(tmp_path)
    output = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/validate_research_csv.py",
            "--bars-csv",
            str(tmp_path / "bars.csv"),
            "--stock-info-csv",
            str(tmp_path / "stock_info.csv"),
            "--fundamentals-csv",
            str(tmp_path / "fundamentals.csv"),
            "--calendar-csv",
            str(tmp_path / "calendar.csv"),
            "--suspensions-csv",
            str(tmp_path / "suspensions.csv"),
            "--index-constituents-csv",
            str(tmp_path / "index_constituents.csv"),
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

    payload = json.loads((output / "csv_validation.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["status"] == "PASS"


def test_validate_research_csv_cli_returns_nonzero_on_block(tmp_path: Path) -> None:
    bars = _bars()
    bars = bars.drop(columns=["close"])
    bars.to_csv(tmp_path / "bars.csv", index=False)
    output = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/validate_research_csv.py",
            "--bars-csv",
            str(tmp_path / "bars.csv"),
            "--output-dir",
            str(output),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output / "csv_validation.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["status"] == "BLOCK"


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
