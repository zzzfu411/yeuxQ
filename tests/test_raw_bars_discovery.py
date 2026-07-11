from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pandas as pd

from quantify.data.raw_bars_discovery import (
    build_raw_bars_discovery_report,
    write_raw_bars_dropzone_kit,
    write_raw_bars_discovery_report,
)


def test_raw_bars_discovery_passes_usable_candidate_without_writing_bars(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "out"
    config = tmp_path / "research_recent.yaml"
    raw = raw_dir / "broker_daily_bars.csv"
    _write_config(config, tmp_path / "recent.db")
    raw_dir.mkdir()
    _bars().to_csv(raw, index=False)

    report = build_raw_bars_discovery_report(
        search_dirs=[raw_dir],
        config_path=config,
        output_dir=output,
        data_output_dir=data_dir,
        min_symbols=2,
    )
    out = write_raw_bars_discovery_report(report, output)

    payload = json.loads((out / "raw_bars_discovery.json").read_text(encoding="utf-8"))
    markdown = (out / "raw_bars_discovery.md").read_text(encoding="utf-8")

    assert report.status == "PASS"
    assert report.best_candidate == str(raw)
    assert report.candidates[0].symbol_count == 2
    assert report.candidates[0].normalized_row_count == 4
    assert "normalize_vendor_bars.py" in report.next_commands[0]
    assert "--source-qa-answers" in report.next_commands[1]
    assert "--source-qa-evidence-manifest" in report.next_commands[1]
    assert "--require-source-qa-evidence-manifest" in report.next_commands[1]
    assert "--source-qa-answers" in report.next_commands[2]
    assert "--require-source-qa-evidence-manifest" in report.next_commands[2]
    assert not (data_dir / "bars.csv").exists()
    assert payload["status"] == "PASS"
    assert "does not normalize data" in markdown


def test_raw_bars_discovery_accepts_chinese_broker_headers(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    raw = raw_dir / "broker_chinese_daily_bars.csv"
    _write_config(config, tmp_path / "recent.db")
    raw_dir.mkdir()
    _chinese_bars().to_csv(raw, index=False, encoding="gb18030")

    report = build_raw_bars_discovery_report(
        search_dirs=[raw_dir],
        config_path=config,
        data_output_dir=data_dir,
        min_symbols=2,
    )

    assert report.status == "PASS"
    assert report.best_candidate == str(raw)
    assert report.candidates[0].encoding in {"gb18030", "gbk", "cp936"}
    assert report.candidates[0].raw_columns[0] == "证券代码"
    assert report.candidates[0].symbol_count == 2
    assert report.candidates[0].normalized_row_count == 4
    assert not (data_dir / "bars.csv").exists()


def test_raw_bars_discovery_watches_low_symbol_count(tmp_path: Path) -> None:
    raw = tmp_path / "one_symbol.csv"
    config = tmp_path / "research_recent.yaml"
    _write_config(config, tmp_path / "recent.db")
    _bars().query("symbol == '600010.SH'").to_csv(raw, index=False)

    report = build_raw_bars_discovery_report(
        search_dirs=[raw],
        config_path=config,
        min_symbols=2,
    )

    assert report.status == "WATCH"
    assert report.candidates[0].status == "WATCH"
    assert "SYMBOL_COUNT_BELOW_TARGET" in report.candidates[0].message


def test_raw_bars_discovery_blocks_when_no_candidate_found(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    data_dir = tmp_path / "data_exports"
    dropzone = data_dir / "raw"
    _write_config(config, tmp_path / "recent.db")

    report = build_raw_bars_discovery_report(
        search_dirs=[tmp_path / "missing"],
        config_path=config,
        data_output_dir=data_dir,
        min_symbols=2,
    )

    assert report.status == "BLOCK"
    assert report.best_candidate == ""
    assert report.dropzone_kit.dropzone_dir == str(dropzone)
    assert report.dropzone_kit.readme_path == str(dropzone / "README_raw_bars_dropzone.md")
    assert "write-dropzone-kit" in report.next_commands[0]
    assert str(dropzone) in report.next_commands[1]
    assert any(str(dropzone) in action for action in report.next_actions)


def test_raw_bars_discovery_writes_dropzone_kit_without_writing_bars(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "out"
    _write_config(config, tmp_path / "recent.db")

    report = build_raw_bars_discovery_report(
        search_dirs=[data_dir / "raw"],
        config_path=config,
        output_dir=output,
        data_output_dir=data_dir,
        min_symbols=2,
    )
    readme = write_raw_bars_dropzone_kit(report)
    payload_dir = write_raw_bars_discovery_report(report, output)
    markdown = readme.read_text(encoding="utf-8")
    payload = json.loads((payload_dir / "raw_bars_discovery.json").read_text(encoding="utf-8"))

    assert readme == data_dir / "raw" / "README_raw_bars_dropzone.md"
    assert readme.exists()
    assert (data_dir / "source_qa_evidence").is_dir()
    assert "Raw Bars Dropzone Kit" in markdown
    assert "run_ohlcv_intake_closeout.py" in markdown
    assert "Do not fabricate" in markdown
    assert payload["dropzone_kit"]["readme_path"] == str(readme)
    assert not (data_dir / "bars.csv").exists()


def test_raw_bars_discovery_reports_zip_archive_without_extracting(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    archive = raw_dir / "broker_export.zip"
    _write_config(config, tmp_path / "recent.db")
    raw_dir.mkdir()
    csv_payload = _bars().to_csv(index=False)
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("broker_daily_bars.csv", csv_payload)

    report = build_raw_bars_discovery_report(
        search_dirs=[raw_dir],
        config_path=config,
        data_output_dir=data_dir,
        min_symbols=2,
    )

    assert report.status == "BLOCK"
    assert report.best_candidate == ""
    assert report.candidates[0].path == str(archive)
    assert report.candidates[0].encoding == "zip"
    assert report.candidates[0].raw_columns == ["broker_daily_bars.csv"]
    assert report.candidates[0].raw_sha256
    assert "extract" in report.candidates[0].message.lower()
    assert any("Extract the retained raw daily-bars CSV" in item for item in report.next_actions)
    assert not (data_dir / "bars.csv").exists()


def test_raw_bars_discovery_scans_raw_bars_csv_name(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    raw_dir = data_dir / "raw"
    raw = raw_dir / "bars.csv"
    config = tmp_path / "research_recent.yaml"
    _write_config(config, tmp_path / "recent.db")
    raw_dir.mkdir(parents=True)
    _bars().to_csv(raw, index=False)

    report = build_raw_bars_discovery_report(
        search_dirs=[raw_dir],
        config_path=config,
        data_output_dir=data_dir,
        min_symbols=2,
    )

    assert report.status == "PASS"
    assert report.best_candidate == str(raw)


def test_raw_bars_discovery_cli_writes_report(tmp_path: Path) -> None:
    raw = tmp_path / "broker_daily_bars.csv"
    output = tmp_path / "out"
    config = tmp_path / "research_recent.yaml"
    _write_config(config, tmp_path / "recent.db")
    _bars().to_csv(raw, index=False)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_raw_bars_discovery.py",
            "--search-dir",
            str(raw),
            "--config",
            str(config),
            "--output-dir",
            str(output),
            "--data-output-dir",
            str(tmp_path / "data_exports"),
            "--min-symbols",
            "2",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output / "raw_bars_discovery.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["status"] == "PASS"
    assert payload["best_candidate"] == str(raw)


def test_raw_bars_discovery_cli_can_write_dropzone_kit_on_block(tmp_path: Path) -> None:
    output = tmp_path / "out"
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    _write_config(config, tmp_path / "recent.db")

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_raw_bars_discovery.py",
            "--search-dir",
            str(data_dir / "raw"),
            "--config",
            str(config),
            "--output-dir",
            str(output),
            "--data-output-dir",
            str(data_dir),
            "--write-dropzone-kit",
            "--min-symbols",
            "2",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    payload = json.loads((output / "raw_bars_discovery.json").read_text(encoding="utf-8"))
    assert payload["candidates"][0]["exists"] is True
    assert (data_dir / "raw" / "README_raw_bars_dropzone.md").exists()
    assert not (data_dir / "bars.csv").exists()


def _write_config(path: Path, cache: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "research:",
                '  start: "2024-01-02"',
                '  end: "2024-01-03"',
                "  allow_demo_data: false",
                "data:",
                "  source: csv",
                f"  cache_path: '{cache}'",
                "  adjust: qfq",
            ]
        ),
        encoding="utf-8",
    )


def _bars() -> pd.DataFrame:
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
