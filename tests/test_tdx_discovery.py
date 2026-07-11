from __future__ import annotations

import json
from pathlib import Path
import struct
import subprocess
import sys

from quantify.data.tdx_discovery import (
    build_tdx_day_discovery_report,
    write_tdx_day_discovery_report,
)


def test_tdx_day_discovery_passes_usable_local_vipdoc(tmp_path: Path) -> None:
    input_dir = tmp_path / "vipdoc"
    config = tmp_path / "research_recent.yaml"
    _write_day_file(input_dir / "sh" / "lday" / "sh600001.day", symbol_base=10.0)
    _write_day_file(input_dir / "sz" / "lday" / "sz000001.day", symbol_base=20.0)
    _write_config(config, tmp_path / "recent.db")

    report = build_tdx_day_discovery_report(
        search_dirs=[input_dir],
        config_path=config,
        output_dir=tmp_path / "out",
        data_output_dir=tmp_path / "data_exports",
        min_symbols=2,
    )
    out = write_tdx_day_discovery_report(report, tmp_path / "out")

    payload = json.loads((out / "tdx_day_discovery.json").read_text(encoding="utf-8"))
    markdown = (out / "tdx_day_discovery.md").read_text(encoding="utf-8")
    assert payload["status"] == "PASS"
    assert payload["best_root"] == str(input_dir)
    assert payload["roots"][0]["symbol_count"] == 2
    assert payload["roots"][0]["start"] == "2024-01-02"
    assert payload["roots"][0]["end"] == "2024-01-03"
    assert "convert_tdx_day.py" in "\n".join(payload["next_commands"])
    assert f"--output-dir {tmp_path / 'out'}" in "\n".join(payload["next_commands"])
    assert "--as-of 2026-06-08" not in "\n".join(payload["next_commands"])
    assert "not a data license review" in markdown


def test_tdx_day_discovery_includes_optional_as_of_in_next_commands(tmp_path: Path) -> None:
    input_dir = tmp_path / "vipdoc"
    config = tmp_path / "research_recent.yaml"
    _write_day_file(input_dir / "sh" / "lday" / "sh600001.day", symbol_base=10.0)
    _write_day_file(input_dir / "sz" / "lday" / "sz000001.day", symbol_base=20.0)
    _write_config(config, tmp_path / "recent.db")

    report = build_tdx_day_discovery_report(
        search_dirs=[input_dir],
        config_path=config,
        output_dir=tmp_path / "custom_out",
        data_output_dir=tmp_path / "data_exports",
        min_symbols=2,
        as_of="2026-06-09",
    )

    commands = "\n".join(report.next_commands)
    assert "--as-of 2026-06-09" in commands
    assert f"--output-dir {tmp_path / 'custom_out'}" in commands


def test_tdx_day_discovery_watches_low_symbol_count(tmp_path: Path) -> None:
    input_dir = tmp_path / "vipdoc"
    config = tmp_path / "research_recent.yaml"
    _write_day_file(input_dir / "sh" / "lday" / "sh600001.day", symbol_base=10.0)
    _write_config(config, tmp_path / "recent.db")

    report = build_tdx_day_discovery_report(
        search_dirs=[input_dir],
        config_path=config,
        min_symbols=2,
    )

    assert report.status == "WATCH"
    assert report.roots[0].status == "WATCH"
    assert "below min_symbols" in report.roots[0].message


def test_tdx_day_discovery_blocks_missing_roots(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    _write_config(config, tmp_path / "recent.db")

    report = build_tdx_day_discovery_report(
        search_dirs=[tmp_path / "missing"],
        config_path=config,
        min_symbols=2,
    )

    assert report.status == "BLOCK"
    assert report.roots[0].exists is False
    assert "search-dir" in report.next_commands[0]


def test_tdx_day_discovery_cli_writes_report(tmp_path: Path) -> None:
    input_dir = tmp_path / "vipdoc"
    output = tmp_path / "out"
    config = tmp_path / "research_recent.yaml"
    _write_day_file(input_dir / "sh" / "lday" / "sh600001.day", symbol_base=10.0)
    _write_config(config, tmp_path / "recent.db")

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_tdx_day_discovery.py",
            "--search-dir",
            str(input_dir),
            "--config",
            str(config),
            "--output-dir",
            str(output),
            "--min-symbols",
            "1",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output / "tdx_day_discovery.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["status"] == "PASS"


def _write_config(path: Path, cache: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "research:",
                '  start: "2024-01-02"',
                '  end: "2024-01-03"',
                "  allow_demo_data: false",
                "data:",
                "  source: akshare",
                f"  cache_path: '{cache}'",
                "  adjust: qfq",
            ]
        ),
        encoding="utf-8",
    )


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
