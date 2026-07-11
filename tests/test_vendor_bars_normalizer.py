from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.vendor_bars_normalizer import (
    normalize_vendor_bars,
    write_vendor_bars_normalization_report,
)


def test_normalize_vendor_bars_accepts_english_schema(tmp_path: Path) -> None:
    raw = tmp_path / "raw_bars.csv"
    output = tmp_path / "data_exports"
    _english_bars().to_csv(raw, index=False)

    report = normalize_vendor_bars(
        input_path=raw,
        output_dir=output,
        start="2024-01-02",
        end="2024-01-03",
        min_symbols=2,
    )

    bars = pd.read_csv(output / "bars.csv", dtype={"symbol": str})
    assert report.status == "PASS"
    assert report.symbol_count == 2
    assert report.normalized_start == "2024-01-02"
    assert report.normalized_end == "2024-01-03"
    assert report.raw_size_bytes == raw.stat().st_size
    assert report.raw_sha256 == _sha256(raw)
    assert report.raw_modified_at_utc
    assert bars.columns.tolist() == [
        "symbol",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]
    assert bars["symbol"].tolist() == ["600010", "600010", "000010", "000010"]


def test_normalize_vendor_bars_accepts_chinese_broker_schema(tmp_path: Path) -> None:
    raw = tmp_path / "raw_chinese_bars.csv"
    output = tmp_path / "data_exports"
    _chinese_bars().to_csv(raw, index=False)

    report = normalize_vendor_bars(
        input_path=raw,
        output_dir=output,
        start="2024-01-02",
        end="2024-01-03",
        min_symbols=2,
    )

    bars = pd.read_csv(output / "bars.csv", dtype={"symbol": str})
    assert report.status == "PASS"
    assert report.raw_columns[0] == "证券代码"
    assert bars["date"].tolist() == ["2024-01-02", "2024-01-03", "2024-01-02", "2024-01-03"]
    assert bars["symbol"].tolist() == ["600010", "600010", "000010", "000010"]


def test_normalize_vendor_bars_auto_detects_broker_encoding(tmp_path: Path) -> None:
    raw = tmp_path / "raw_chinese_gb18030.csv"
    output = tmp_path / "data_exports"
    _chinese_bars().to_csv(raw, index=False, encoding="gb18030")

    report = normalize_vendor_bars(
        input_path=raw,
        output_dir=output,
        encoding="auto",
        start="2024-01-02",
        end="2024-01-03",
        min_symbols=2,
    )

    bars = pd.read_csv(output / "bars.csv", dtype={"symbol": str})
    assert report.status == "PASS"
    assert report.encoding in {"gb18030", "gbk", "cp936"}
    assert report.raw_columns[0] in {"证券代码", "璇佸埜浠ｇ爜"}
    assert bars["symbol"].tolist() == ["600010", "600010", "000010", "000010"]


def test_normalize_vendor_bars_missing_required_column_blocks(tmp_path: Path) -> None:
    raw = tmp_path / "raw_bars.csv"
    output = tmp_path / "data_exports"
    _english_bars().drop(columns=["close"]).to_csv(raw, index=False)

    report = normalize_vendor_bars(input_path=raw, output_dir=output, min_symbols=2)

    assert report.status == "BLOCK"
    assert not (output / "bars.csv").exists()
    assert any(finding.code == "RAW_VENDOR_BARS_INVALID" for finding in report.findings)


def test_normalize_vendor_bars_missing_amount_watches_and_fills_zero(tmp_path: Path) -> None:
    raw = tmp_path / "raw_bars.csv"
    output = tmp_path / "data_exports"
    _english_bars().drop(columns=["amount"]).to_csv(raw, index=False)

    report = normalize_vendor_bars(input_path=raw, output_dir=output, min_symbols=2)

    bars = pd.read_csv(output / "bars.csv")
    assert report.status == "WATCH"
    assert set(bars["amount"].tolist()) == {0.0}
    assert any(finding.code == "RAW_VENDOR_BARS_AMOUNT_MISSING" for finding in report.findings)
    assert any(
        finding.code == "NORMALIZED_VENDOR_BARS_NON_POSITIVE_LIQUIDITY"
        for finding in report.findings
    )


def test_normalize_vendor_bars_preserves_raw_fingerprint_when_output_overwrites_input(
    tmp_path: Path,
) -> None:
    output = tmp_path / "data_exports"
    output.mkdir()
    raw = output / "bars.csv"
    _english_bars().to_csv(raw, index=False)
    raw_sha256 = _sha256(raw)
    raw_size_bytes = raw.stat().st_size

    report = normalize_vendor_bars(input_path=raw, output_dir=output, min_symbols=2)

    assert report.status == "PASS"
    assert report.raw_sha256 == raw_sha256
    assert report.raw_size_bytes == raw_size_bytes
    assert _sha256(raw) != raw_sha256


def test_vendor_bars_normalization_report_and_cli_write_outputs(tmp_path: Path) -> None:
    raw = tmp_path / "raw_bars.csv"
    output = tmp_path / "data_exports"
    reports = tmp_path / "reports"
    _english_bars().to_csv(raw, index=False)

    report = normalize_vendor_bars(input_path=raw, output_dir=output, min_symbols=2)
    out = write_vendor_bars_normalization_report(report, reports)

    assert (out / "vendor_bars_normalization.json").exists()
    markdown = (out / "vendor_bars_normalization.md").read_text(encoding="utf-8")
    assert "not source QA" in markdown
    assert "live trading permission" in markdown
    assert "Raw sha256" in markdown

    cli_output = tmp_path / "cli_data_exports"
    completed = subprocess.run(
        [
            sys.executable,
            "examples/normalize_vendor_bars.py",
            "--input",
            str(raw),
            "--output-dir",
            str(cli_output),
            "--report-dir",
            str(tmp_path / "cli_reports"),
            "--encoding",
            "auto",
            "--min-symbols",
            "2",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads(
        (tmp_path / "cli_reports" / "vendor_bars_normalization.json").read_text(encoding="utf-8")
    )
    assert completed.returncode == 0
    assert payload["status"] == "PASS"
    assert payload["encoding"] in {"utf-8-sig", "utf-8"}
    assert payload["raw_sha256"] == _sha256(raw)
    assert payload["raw_size_bytes"] == raw.stat().st_size
    assert payload["raw_modified_at_utc"]
    assert (cli_output / "bars.csv").exists()


def _english_bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["600010.SH", "600010.SH", "SZ000010", "SZ000010"],
            "date": ["2024-01-02", "2024-01-03", "2024-01-02", "2024-01-03"],
            "open": [11.0, 11.1, 21.0, 21.1],
            "high": [11.5, 11.6, 21.5, 21.6],
            "low": [10.8, 11.0, 20.8, 21.0],
            "close": [11.2, 11.3, 21.2, 21.3],
            "volume": [1_500_000, 1_600_000, 2_500_000, 2_600_000],
            "amount": [16_800_000, 18_080_000, 53_000_000, 55_380_000],
        }
    )


def _chinese_bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "证券代码": ["600010.SH", "600010.SH", "SZ000010", "SZ000010"],
            "交易日期": [20240102, 20240103, 20240102, 20240103],
            "开盘价": [11.0, 11.1, 21.0, 21.1],
            "最高价": [11.5, 11.6, 21.5, 21.6],
            "最低价": [10.8, 11.0, 20.8, 21.0],
            "收盘价": [11.2, 11.3, 21.2, 21.3],
            "成交量": [1_500_000, 1_600_000, 2_500_000, 2_600_000],
            "成交额": [16_800_000, 18_080_000, 53_000_000, 55_380_000],
        }
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
