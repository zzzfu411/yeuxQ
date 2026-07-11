from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.ops import build_real_data_bootstrap_report, write_real_data_bootstrap_report
from quantify.utils.config import Config


def test_real_data_bootstrap_blocks_missing_cache(tmp_path: Path) -> None:
    cache = tmp_path / "missing.db"
    storage = BarStorage(cache)
    cfg = _cfg(cache, allow_demo_data=False)

    report = build_real_data_bootstrap_report(
        DataProvider(storage),
        cfg,
        config_path=tmp_path / "research.yaml",
        cache_path=cache,
        as_of="2024-07-01",
        cache_exists_before_open=False,
        cache_size_before_open=0,
    )

    assert report.decision == "BLOCK"
    assert report.cache_exists is False
    assert any(finding.code == "CACHE_MISSING" for finding in report.findings)


def test_real_data_bootstrap_passes_ready_real_cache(tmp_path: Path) -> None:
    cache = tmp_path / "real.db"
    storage = BarStorage(cache)
    _seed_real_like_data(storage, "2024-01-01", periods=130, symbols=60)
    cfg = _cfg(cache, allow_demo_data=False)

    report = build_real_data_bootstrap_report(
        DataProvider(storage),
        cfg,
        config_path=tmp_path / "research.yaml",
        cache_path=cache,
        as_of="2024-07-01",
        min_symbols=50,
        min_trading_days=120,
        max_staleness_days=10,
    )
    out = write_real_data_bootstrap_report(report, tmp_path / "out")

    assert report.decision == "PASS"
    assert report.symbol_count == 60
    assert (out / "real_data_bootstrap.json").exists()
    assert "Real Data Bootstrap" in (out / "real_data_bootstrap.md").read_text(encoding="utf-8")


def test_real_data_bootstrap_warns_when_demo_fallback_enabled(tmp_path: Path) -> None:
    cache = tmp_path / "real.db"
    storage = BarStorage(cache)
    _seed_real_like_data(storage, "2024-01-01", periods=130, symbols=60)
    cfg = _cfg(cache, allow_demo_data=True)

    report = build_real_data_bootstrap_report(
        DataProvider(storage),
        cfg,
        config_path=tmp_path / "research.yaml",
        cache_path=cache,
        as_of="2024-07-01",
    )

    assert report.decision == "WATCH"
    assert any(finding.code == "DEMO_FALLBACK_ENABLED" for finding in report.findings)


def test_real_data_bootstrap_cli_writes_outputs(tmp_path: Path) -> None:
    cache = tmp_path / "real.db"
    storage = BarStorage(cache)
    _seed_real_like_data(storage, "2024-01-01", periods=130, symbols=60)
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(cache), encoding="utf-8")
    out = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_real_data_bootstrap.py",
            "--config",
            str(cfg_path),
            "--output-dir",
            str(out),
            "--as-of",
            "2024-07-01",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((out / "real_data_bootstrap.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["decision"] == "PASS"


def _cfg(cache_path: Path, *, allow_demo_data: bool) -> Config:
    return Config(
        {
            "research": {
                "start": "2024-01-01",
                "end": "2024-06-28",
                "in_sample_end": "2024-04-30",
                "out_sample_start": "2024-05-01",
                "allow_demo_data": allow_demo_data,
            },
            "data": {"source": "csv", "cache_path": str(cache_path)},
        }
    )


def _cfg_yaml(cache: Path) -> str:
    return f"""
research:
  start: "2024-01-01"
  end: "2024-06-28"
  in_sample_end: "2024-04-30"
  out_sample_start: "2024-05-01"
  allow_demo_data: false
data:
  source: csv
  cache_path: "{cache.as_posix()}"
"""


def _seed_real_like_data(storage: BarStorage, start: str, *, periods: int, symbols: int) -> None:
    dates = pd.bdate_range(start, periods=periods)
    names = [f"{600000 + idx:06d}" for idx in range(symbols)]
    storage.save_calendar([date.date().isoformat() for date in dates])
    storage.save_stock_info(
        pd.DataFrame(
            {
                "symbol": names,
                "name": [f"Real{idx}" for idx in range(symbols)],
                "exchange": ["SSE"] * symbols,
                "list_date": ["2020-01-01"] * symbols,
                "delist_date": [""] * symbols,
                "industry": ["test"] * symbols,
                "is_st": [0] * symbols,
            }
        )
    )
    rows = []
    for idx, symbol in enumerate(names):
        base = 10 + idx * 0.01
        for day, dt in enumerate(dates):
            close = base * (1 + 0.0005) ** day
            rows.append(
                {
                    "symbol": symbol,
                    "date": dt.date().isoformat(),
                    "open": close * 0.999,
                    "high": close * 1.002,
                    "low": close * 0.998,
                    "close": close,
                    "volume": 1_000_000,
                    "amount": close * 1_000_000,
                }
            )
    storage.save_bars(pd.DataFrame(rows))
