from __future__ import annotations

import json
from pathlib import Path
import struct
import subprocess
import sys

import pandas as pd

from quantify.data.csv_contract import validate_research_csvs
from quantify.data.tdx_day import export_tdx_day_to_csv


def test_export_tdx_day_to_csv_writes_valid_bars_stock_info_and_calendar(tmp_path: Path) -> None:
    input_dir = tmp_path / "vipdoc"
    _write_day_file(input_dir / "sh" / "lday" / "sh600001.day", symbol_base=10.0)
    _write_day_file(input_dir / "sz" / "lday" / "sz000001.day", symbol_base=20.0)
    output = tmp_path / "data_exports"

    report = export_tdx_day_to_csv(
        input_dir=input_dir,
        output_dir=output,
        start="2024-01-02",
        end="2024-01-03",
    )
    validation = validate_research_csvs(
        bars_csv=output / "bars.csv",
        stock_info_csv=output / "stock_info.csv",
        calendar_csv=output / "calendar.csv",
        start="2024-01-02",
        end="2024-01-03",
        min_symbols=2,
    )

    bars = pd.read_csv(output / "bars.csv")
    stock_info = pd.read_csv(output / "stock_info.csv")
    calendar = pd.read_csv(output / "calendar.csv")
    assert report.status == "PASS"
    assert report.symbol_count == 2
    assert report.row_count == 4
    assert set(bars["symbol"].astype(str).str.zfill(6)) == {"000001", "600001"}
    assert bars["date"].min() == "2024-01-02"
    assert bars["date"].max() == "2024-01-03"
    assert set(stock_info["exchange"]) == {"SSE", "SZSE"}
    assert calendar["date"].tolist() == ["2024-01-02", "2024-01-03"]
    assert validation.status == "WATCH"
    assert not any(finding.code == "BARS_CSV_INVALID" for finding in validation.findings)
    assert (output / "tdx_day_export.json").exists()
    assert (output / "tdx_day_export.md").exists()


def test_export_tdx_day_filters_symbols_and_blocks_empty_selection(tmp_path: Path) -> None:
    input_dir = tmp_path / "vipdoc"
    _write_day_file(input_dir / "sh" / "lday" / "sh600001.day", symbol_base=10.0)

    report = export_tdx_day_to_csv(
        input_dir=input_dir,
        output_dir=tmp_path / "out",
        symbols=["000001"],
    )

    assert report.status == "BLOCK"
    assert report.discovered_files == 1
    assert report.symbol_count == 0
    assert pd.read_csv(tmp_path / "out" / "bars.csv").empty


def test_convert_tdx_day_cli_writes_outputs(tmp_path: Path) -> None:
    input_dir = tmp_path / "vipdoc"
    output = tmp_path / "data_exports"
    _write_day_file(input_dir / "sh" / "lday" / "sh600001.day", symbol_base=10.0)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/convert_tdx_day.py",
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output),
            "--start",
            "2024-01-02",
            "--end",
            "2024-01-03",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output / "tdx_day_export.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["status"] == "PASS"
    assert (output / "bars.csv").exists()


def _write_day_file(path: Path, *, symbol_base: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = struct.Struct("<IIIIIfII")
    rows = [
        record.pack(
            20240102,
            int(symbol_base * 100),
            int((symbol_base + 0.5) * 100),
            int((symbol_base - 0.2) * 100),
            int((symbol_base + 0.2) * 100),
            float((symbol_base + 0.2) * 1_000_000),
            1_000_000,
            0,
        ),
        record.pack(
            20240103,
            int((symbol_base + 0.2) * 100),
            int((symbol_base + 0.8) * 100),
            int((symbol_base + 0.1) * 100),
            int((symbol_base + 0.6) * 100),
            float((symbol_base + 0.6) * 1_100_000),
            1_100_000,
            0,
        ),
    ]
    path.write_bytes(b"".join(rows))
