from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.market import detect_market_regime, write_market_regime_report


def test_market_regime_detects_risk_on_market(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "risk_on.db")
    _seed_market(storage, _steady_up_prices())

    report = detect_market_regime(DataProvider(storage), "2024-01-01", "2024-08-30")
    out = write_market_regime_report(report, tmp_path / "out")

    assert report.status == "PASS"
    assert report.label == "risk_on"
    assert report.metrics["return_60d"] is not None
    assert (out / "market_regime.json").exists()
    assert "Market Regime" in (out / "market_regime.md").read_text(encoding="utf-8")


def test_market_regime_detects_risk_off_drawdown(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "risk_off.db")
    _seed_market(storage, _drawdown_prices())

    report = detect_market_regime(DataProvider(storage), "2024-01-01", "2024-08-30")

    assert report.status == "WATCH"
    assert report.label == "risk_off"
    assert float(report.metrics["max_drawdown"] or 0.0) >= 0.18
    assert any("drawdown" in finding.lower() for finding in report.findings)


def test_market_regime_cli_writes_artifacts(tmp_path: Path) -> None:
    cache_path = tmp_path / "research.db"
    storage = BarStorage(cache_path)
    _seed_market(storage, _steady_up_prices())
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(cache_path), encoding="utf-8")
    output_dir = tmp_path / "regime"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_market_regime.py",
            "--config",
            str(cfg_path),
            "--output-dir",
            str(output_dir),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert (output_dir / "market_regime.json").exists()
    assert (output_dir / "market_regime.md").exists()


def _steady_up_prices() -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=160)
    rows = []
    for idx in range(6):
        base = 10.0 + idx
        for day, date in enumerate(dates):
            close = base * (1 + 0.0015 + idx * 0.0001) ** day
            rows.append(_bar(f"AAA{idx}", date, close))
    return pd.DataFrame(rows)


def _drawdown_prices() -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=160)
    rows = []
    for idx in range(6):
        base = 10.0 + idx
        for day, date in enumerate(dates):
            if day < 80:
                close = base * (1 + 0.001) ** day
            else:
                close = base * (1 + 0.001) ** 80 * (0.995 - idx * 0.0005) ** (day - 80)
            rows.append(_bar(f"AAA{idx}", date, close))
    return pd.DataFrame(rows)


def _bar(symbol: str, date: pd.Timestamp, close: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "date": date.date().isoformat(),
        "open": close * 0.999,
        "high": close * 1.002,
        "low": close * 0.998,
        "close": close,
        "volume": 1_000_000,
        "amount": close * 1_000_000,
    }


def _seed_market(storage: BarStorage, bars: pd.DataFrame) -> None:
    dates = sorted(bars["date"].unique().tolist())
    symbols = sorted(bars["symbol"].unique().tolist())
    storage.save_calendar(dates)
    storage.save_stock_info(
        pd.DataFrame(
            {
                "symbol": symbols,
                "name": symbols,
                "exchange": ["SSE"] * len(symbols),
                "list_date": ["2020-01-01"] * len(symbols),
                "delist_date": [""] * len(symbols),
                "industry": ["test"] * len(symbols),
                "is_st": [0] * len(symbols),
            }
        )
    )
    storage.save_bars(bars)


def _cfg_yaml(cache_path: Path) -> str:
    return f"""
research:
  start: "2024-01-01"
  end: "2024-08-30"
  initial_cash: 1000000.0
  rebalance: monthly
  allow_demo_data: true
data:
  source: csv
  cache_path: "{cache_path.as_posix()}"
universe:
  mode: all_a
  index_code: "000906"
  include_st: false
  min_history_days: 20
strategy:
  n_holdings: 5
  max_weight: 0.10
risk:
  max_drawdown_stop: 0.2
broker:
  commission_rate: 0.0
  min_commission: 0.0
  stamp_tax: 0.0
  slippage_bps: 0.0
  price_limit_pct: 0.10
  lot_size: 100
output:
  results_dir: "{cache_path.parent.as_posix()}"
"""
