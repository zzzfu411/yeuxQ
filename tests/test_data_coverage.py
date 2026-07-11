from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.ops import analyze_data_coverage, write_data_coverage_report


def test_data_coverage_passes_full_symbol_history(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "coverage.db")
    _seed(storage, missing_tail_for_last=False)

    report = analyze_data_coverage(DataProvider(storage), "2024-01-01", "2024-01-12")
    out = write_data_coverage_report(report, tmp_path / "out")

    assert report.status == "PASS"
    assert report.full_coverage_symbol_count == 3
    assert (out / "data_coverage.json").exists()
    assert (out / "data_coverage.csv").exists()


def test_data_coverage_warns_on_short_and_stale_symbols(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "coverage.db")
    _seed(storage, missing_tail_for_last=True)

    report = analyze_data_coverage(DataProvider(storage), "2024-01-01", "2024-01-12")

    assert report.status == "WATCH"
    assert report.short_history_symbol_count == 1
    assert report.stale_symbol_count == 1
    assert any("less than" in finding for finding in report.findings)


def test_data_coverage_cli_writes_outputs(tmp_path: Path) -> None:
    cache = tmp_path / "coverage.db"
    storage = BarStorage(cache)
    _seed(storage, missing_tail_for_last=False)
    cfg = tmp_path / "research.yaml"
    cfg.write_text(_cfg_yaml(cache), encoding="utf-8")
    out = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_data_coverage.py",
            "--config",
            str(cfg),
            "--output-dir",
            str(out),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert (out / "data_coverage.md").exists()


def _seed(storage: BarStorage, *, missing_tail_for_last: bool) -> None:
    dates = pd.bdate_range("2024-01-01", periods=10)
    symbols = ["600001", "600002", "600003"]
    storage.save_calendar([date.date().isoformat() for date in dates])
    storage.save_stock_info(pd.DataFrame({"symbol": symbols, "name": symbols}))
    rows = []
    for symbol in symbols:
        symbol_dates = dates[:-3] if missing_tail_for_last and symbol == "600003" else dates
        for idx, dt in enumerate(symbol_dates):
            close = 10 + idx * 0.1
            rows.append(
                {
                    "symbol": symbol,
                    "date": dt.date().isoformat(),
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 1_000_000,
                    "amount": close * 1_000_000,
                }
            )
    storage.save_bars(pd.DataFrame(rows))


def _cfg_yaml(cache: Path) -> str:
    return f"""
research:
  start: "2024-01-01"
  end: "2024-01-12"
data:
  cache_path: "{cache.as_posix()}"
"""
