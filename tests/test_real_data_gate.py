from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.ops import evaluate_real_data_gate, write_real_data_gate
from quantify.research.demo_data import seed_demo_data


def test_real_data_gate_blocks_demo_data(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "demo.db")
    seed_demo_data(storage, "2024-01-01", "2024-06-30")

    result = evaluate_real_data_gate(
        DataProvider(storage),
        "2024-01-01",
        "2024-06-30",
        as_of="2024-07-01",
    )

    assert result.decision == "BLOCK"
    assert any(finding.code == "DEMO_DATA" for finding in result.findings)


def test_real_data_gate_blocks_mixed_demo_and_real_data(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "mixed.db")
    _seed_real_like_data(storage, "2024-01-01", periods=130, symbols=60)
    _add_demo_symbol(storage, "2024-01-01", periods=130)

    result = evaluate_real_data_gate(
        DataProvider(storage),
        "2024-01-01",
        "2024-06-28",
        as_of="2024-07-01",
        min_symbols=50,
        min_trading_days=120,
        max_staleness_days=10,
    )

    assert result.demo_data_used is True
    assert result.decision == "BLOCK"
    assert any(finding.code == "DEMO_DATA" for finding in result.findings)


def test_real_data_gate_blocks_stale_real_data(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "real.db")
    _seed_real_like_data(storage, "2024-01-01", periods=130, symbols=60)

    result = evaluate_real_data_gate(
        DataProvider(storage),
        "2024-01-01",
        "2024-06-28",
        as_of="2024-08-01",
        min_symbols=50,
        min_trading_days=120,
        max_staleness_days=10,
    )

    assert result.decision == "BLOCK"
    assert any(finding.code == "STALE_DATA" for finding in result.findings)


def test_real_data_gate_passes_recent_broad_real_data(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "real.db")
    _seed_real_like_data(storage, "2024-01-01", periods=130, symbols=60)

    result = evaluate_real_data_gate(
        DataProvider(storage),
        "2024-01-01",
        "2024-06-28",
        as_of="2024-07-01",
        min_symbols=50,
        min_trading_days=120,
        max_staleness_days=10,
    )
    out = write_real_data_gate(result, tmp_path / "gate")

    assert result.decision == "PASS"
    assert (out / "real_data_gate.json").exists()
    assert "Real Data Gate" in (out / "real_data_gate.md").read_text(encoding="utf-8")


def test_real_data_gate_cli_writes_outputs(tmp_path: Path) -> None:
    cache = tmp_path / "real.db"
    storage = BarStorage(cache)
    _seed_real_like_data(storage, "2024-01-01", periods=130, symbols=60)
    cfg = tmp_path / "research.yaml"
    cfg.write_text(_cfg_yaml(cache), encoding="utf-8")
    out = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_real_data_gate.py",
            "--config",
            str(cfg),
            "--output-dir",
            str(out),
            "--as-of",
            "2024-07-01",
            "--min-symbols",
            "50",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert (out / "real_data_gate.json").exists()


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


def _add_demo_symbol(storage: BarStorage, start: str, *, periods: int) -> None:
    dates = pd.bdate_range(start, periods=periods)
    storage.save_stock_info(pd.DataFrame({"symbol": ["DEMO001"], "name": ["Demo"]}))
    rows = []
    for day, dt in enumerate(dates):
        close = 20 * (1 + 0.0005) ** day
        rows.append(
            {
                "symbol": "DEMO001",
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


def _cfg_yaml(cache: Path) -> str:
    return f"""
research:
  start: "2024-01-01"
  end: "2024-06-28"
data:
  cache_path: "{cache.as_posix()}"
"""
