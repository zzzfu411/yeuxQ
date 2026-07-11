from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.market import (
    MarketContextIndexMetric,
    build_market_context_snapshot_from_csvs,
    build_market_context_snapshot,
    write_market_context_snapshot,
)


def test_market_context_snapshot_writes_advisory_artifacts(tmp_path: Path) -> None:
    snapshot = build_market_context_snapshot(
        as_of="2026-06-09",
        source="manual review of vendor index closes",
        reviewed_by="tester",
        reviewed_at="2026-06-09",
        index_metrics=[
            MarketContextIndexMetric(
                name="CSI300",
                return_20d=0.02,
                return_60d=0.06,
                return_120d=0.08,
                max_drawdown=0.07,
                annualized_volatility=0.20,
                breadth_above_ma20=0.62,
                breadth_above_ma60=0.58,
            )
        ],
        breadth_note="manual breadth snapshot",
    )
    out = write_market_context_snapshot(snapshot, tmp_path / "out")

    payload = json.loads((out / "market_context_snapshot.json").read_text(encoding="utf-8"))
    markdown = (out / "market_context_snapshot.md").read_text(encoding="utf-8")
    assert snapshot.status == "PASS"
    assert snapshot.label == "risk_on"
    assert payload["artifact_type"] == "market_context_snapshot"
    assert payload["can_replace_market_regime"] is False
    assert payload["can_generate_broker_orders"] is False
    assert "cannot replace `market_regime.json`" in markdown


def test_market_context_snapshot_blocks_missing_source_review_metadata() -> None:
    snapshot = build_market_context_snapshot(
        as_of="2026-06-09",
        source="<source>",
        reviewed_by="",
        reviewed_at="2026-06-09",
        index_metrics=[
            {
                "name": "CSI500",
                "return_20d": -0.02,
                "return_60d": -0.12,
                "max_drawdown": 0.20,
                "annualized_volatility": 0.35,
            }
        ],
    )

    assert snapshot.status == "BLOCK"
    assert snapshot.label == "risk_off"
    assert any("placeholder" in finding for finding in snapshot.findings)
    assert any("reviewed_by" in finding for finding in snapshot.findings)


def test_market_context_snapshot_cli_writes_outputs(tmp_path: Path) -> None:
    out = tmp_path / "snapshot"
    completed = subprocess.run(
        [
            sys.executable,
            "examples/write_market_context_snapshot.py",
            "--output-dir",
            str(out),
            "--as-of",
            "2026-06-09",
            "--source",
            "manual vendor terminal screenshot reviewed offline",
            "--reviewed-by",
            "tester",
            "--reviewed-at",
            "2026-06-09",
            "--index",
            "CSI300,0.01,0.03,0.04,0.08,0.22,0.55,0.50,offline note",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((out / "market_context_snapshot.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["status"] in {"PASS", "WATCH"}
    assert payload["index_metrics"][0]["name"] == "CSI300"
    assert (out / "market_context_snapshot.md").exists()


def test_market_context_snapshot_builds_from_index_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "indices.csv"
    dates = pd.bdate_range("2026-01-01", periods=140)
    rows = []
    for name, base, drift in [("CSI300", 4000.0, 0.0010), ("CSI500", 6000.0, 0.0008)]:
        for idx, date in enumerate(dates):
            rows.append(
                {
                    "index": name,
                    "date": date.date().isoformat(),
                    "close": base * (1 + drift) ** idx,
                    "breadth_above_ma20": 0.65,
                    "breadth_above_ma60": 0.60,
                }
            )
    pd.DataFrame(rows).to_csv(csv_path, index=False)

    snapshot = build_market_context_snapshot_from_csvs(
        csv_paths=[csv_path],
        as_of=dates[-1].date().isoformat(),
        source="local index CSV exported from vendor terminal",
        reviewed_by="tester",
        reviewed_at=dates[-1].date().isoformat(),
    )
    out = write_market_context_snapshot(snapshot, tmp_path / "out_csv")

    payload = json.loads((out / "market_context_snapshot.json").read_text(encoding="utf-8"))
    assert snapshot.status == "PASS"
    assert snapshot.label == "risk_on"
    assert len(payload["index_metrics"]) == 2
    assert payload["metrics"]["return_60d"] is not None
    assert payload["metrics"]["max_drawdown"] == 0.0
    assert "rows=140" in payload["index_metrics"][0]["note"]


def test_market_context_snapshot_csv_missing_close_blocks(tmp_path: Path) -> None:
    csv_path = tmp_path / "bad_indices.csv"
    pd.DataFrame({"date": ["2026-06-09"], "index": ["CSI300"]}).to_csv(csv_path, index=False)

    snapshot = build_market_context_snapshot_from_csvs(
        csv_paths=[csv_path],
        as_of="2026-06-09",
        source="local index CSV exported from vendor terminal",
        reviewed_by="tester",
        reviewed_at="2026-06-09",
    )

    assert snapshot.status == "BLOCK"
    assert any("missing a close column" in finding for finding in snapshot.findings)


def test_market_context_snapshot_cli_accepts_index_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "csi300.csv"
    dates = pd.bdate_range("2026-01-01", periods=90)
    pd.DataFrame(
        {
            "date": [date.date().isoformat() for date in dates],
            "close": [4000.0 * (1.0005**idx) for idx, _date in enumerate(dates)],
        }
    ).to_csv(csv_path, index=False)
    out = tmp_path / "snapshot_csv_cli"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/write_market_context_snapshot.py",
            "--output-dir",
            str(out),
            "--as-of",
            dates[-1].date().isoformat(),
            "--source",
            "local index CSV exported from vendor terminal",
            "--reviewed-by",
            "tester",
            "--reviewed-at",
            dates[-1].date().isoformat(),
            "--index-csv",
            str(csv_path),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((out / "market_context_snapshot.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["index_metrics"][0]["name"] == "csi300"
    assert payload["index_metrics"][0]["return_20d"] is not None
