from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.ops.run_manifest import build_run_manifest, write_run_manifest
from quantify.utils.config import Config


def test_run_manifest_records_config_cache_and_data_version(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    config_path = tmp_path / "research.yaml"
    config_path.write_text("research:\n  start: '2024-01-02'\n", encoding="utf-8")
    storage = BarStorage(cache)
    storage.save_calendar(["2024-01-02"])
    storage.save_stock_info(pd.DataFrame({"symbol": ["600001"], "name": ["A"]}))
    storage.save_bars(
        pd.DataFrame(
            {
                "symbol": ["600001"],
                "date": ["2024-01-02"],
                "open": [10.0],
                "high": [10.2],
                "low": [9.8],
                "close": [10.1],
                "volume": [1000],
                "amount": [10100],
            }
        )
    )
    storage.save_metadata(
        {
            "csv_dataset_fingerprint": "fingerprint-1",
            "raw_vendor_bars_sha256": "raw-fingerprint-1",
        }
    )
    cfg = Config(
        {
            "research": {
                "start": "2024-01-02",
                "end": "2024-01-02",
                "in_sample_end": "2024-01-02",
                "out_sample_start": "2024-01-02",
                "initial_cash": 1_000_000,
                "rebalance": "monthly",
            },
            "data": {"source": "csv", "cache_path": str(cache)},
            "universe": {"mode": "all_a", "index_code": "000906", "include_st": False, "min_history_days": 1},
            "strategy": {"name": "multi_factor", "n_holdings": 10, "max_weight": 0.1},
            "risk": {"max_drawdown_stop": 0.2},
            "broker": {
                "commission_rate": 0.0,
                "stamp_tax": 0.0,
                "slippage_bps": 0.0,
                "price_limit_pct": 0.1,
                "lot_size": 100,
            },
        }
    )

    manifest = build_run_manifest(
        DataProvider(storage),
        cfg,
        storage=storage,
        config_path=config_path,
        demo_data_used=False,
    )
    out = write_run_manifest(manifest, tmp_path / "out")
    payload = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))

    assert payload["config_sha256"]
    assert payload["cache_sha256"]
    assert payload["data_version"]["csv_dataset_fingerprint"] == "fingerprint-1"
    assert payload["data_version"]["raw_vendor_bars_sha256"] == "raw-fingerprint-1"
    assert payload["symbol_count"] == 1
