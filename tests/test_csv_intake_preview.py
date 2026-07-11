from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.csv_contract import write_research_csv_templates
from quantify.data.csv_intake_preview import build_csv_intake_preview, write_csv_intake_preview


def test_csv_intake_preview_passes_template_schema(tmp_path: Path) -> None:
    write_research_csv_templates(tmp_path)

    preview = build_csv_intake_preview(data_dir=tmp_path)
    out = write_csv_intake_preview(preview, tmp_path / "out")

    payload = json.loads((out / "csv_intake_preview.json").read_text(encoding="utf-8"))
    items = {item["role"]: item for item in payload["items"]}
    assert preview.status == "PASS"
    assert items["bars"]["mapped_columns"][:3] == ["symbol", "date", "open"]
    assert items["bars"]["symbol_count"] == 2
    assert (out / "csv_intake_preview.md").exists()


def test_csv_intake_preview_accepts_normal_chinese_columns(tmp_path: Path) -> None:
    _normal_chinese_export(tmp_path)

    preview = build_csv_intake_preview(data_dir=tmp_path)

    items = {item.role: item for item in preview.items}
    assert preview.status == "PASS"
    assert "证券代码" in items["bars"].raw_columns
    assert "symbol" in items["bars"].mapped_columns
    assert items["bars"].symbol_count == 2
    assert items["suspensions"].normalized_rows == 1
    assert items["index_constituents"].symbol_count == 2


def test_csv_intake_preview_preserves_symbol_leading_zero_in_sample_rows(tmp_path: Path) -> None:
    pd.DataFrame(
        {
            "symbol": ["000001", "600001"],
            "date": ["2024-01-02", "2024-01-02"],
            "open": [10.0, 20.0],
            "high": [10.5, 20.5],
            "low": [9.8, 19.8],
            "close": [10.2, 20.2],
            "volume": [1000, 2000],
            "amount": [10_200, 40_400],
        }
    ).to_csv(tmp_path / "bars.csv", index=False)

    preview = build_csv_intake_preview(data_dir=tmp_path, sample_rows=2)

    bars = next(item for item in preview.items if item.role == "bars")
    assert bars.sample_rows[0]["symbol"] == "000001"
    assert bars.symbol_count == 2


def test_csv_intake_preview_auto_detects_gbk_export(tmp_path: Path) -> None:
    _normal_chinese_export(tmp_path, encoding="gbk")

    preview = build_csv_intake_preview(data_dir=tmp_path, encoding="auto")

    items = {item.role: item for item in preview.items}
    assert preview.status == "PASS"
    assert items["bars"].raw_columns[0] == "证券代码"
    assert items["bars"].symbol_count == 2


def test_csv_intake_preview_blocks_missing_required_bars(tmp_path: Path) -> None:
    preview = build_csv_intake_preview(data_dir=tmp_path)

    bars = next(item for item in preview.items if item.role == "bars")
    assert preview.status == "BLOCK"
    assert bars.status == "BLOCK"
    assert "missing" in bars.message
    assert any("bars.csv" in action for action in preview.next_actions)


def test_csv_intake_preview_cli_writes_report_and_returns_nonzero_on_block(tmp_path: Path) -> None:
    output = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_csv_intake_preview.py",
            "--data-dir",
            str(tmp_path),
            "--output-dir",
            str(output),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output / "csv_intake_preview.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["status"] == "BLOCK"


def _normal_chinese_export(root: Path, *, encoding: str = "utf-8") -> None:
    pd.DataFrame(
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
    ).to_csv(root / "bars.csv", index=False, encoding=encoding)
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
    ).to_csv(root / "stock_info.csv", index=False, encoding=encoding)
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
    ).to_csv(root / "fundamentals.csv", index=False, encoding=encoding)
    pd.DataFrame({"交易日期": [20240102, 20240103], "是否开市": ["是", "是"]}).to_csv(
        root / "calendar.csv",
        index=False,
        encoding=encoding,
    )
    pd.DataFrame({"证券代码": ["000001.SZ"], "交易日期": [20240103], "是否停牌": ["是"]}).to_csv(
        root / "suspensions.csv",
        index=False,
        encoding=encoding,
    )
    pd.DataFrame(
        {
            "指数代码": ["000906.SH", "000906.SH"],
            "交易日期": [20240102, 20240102],
            "证券代码": ["600001.SH", "000001.SZ"],
        }
    ).to_csv(root / "index_constituents.csv", index=False, encoding=encoding)
