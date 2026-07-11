from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.market import build_market_index_discovery_report, write_market_index_discovery_report


def test_market_index_discovery_blocks_without_index_csv(tmp_path: Path) -> None:
    report = build_market_index_discovery_report(
        search_dirs=[tmp_path / "indices"],
        output_dir=tmp_path / "out",
        as_of="2026-06-10",
    )
    out = write_market_index_discovery_report(report, tmp_path / "out")

    payload = json.loads((out / "market_index_discovery.json").read_text(encoding="utf-8"))
    markdown = (out / "market_index_discovery.md").read_text(encoding="utf-8")
    assert report.status == "BLOCK"
    assert payload["best_candidate"] == ""
    assert "No candidate index CSV files" in payload["candidates"][0]["findings"][0]
    assert "Market Index CSV Discovery" in markdown


def test_market_index_discovery_finds_reviewable_long_form_index_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "indices" / "a_share_indices.csv"
    csv_path.parent.mkdir()
    dates = pd.bdate_range("2026-01-01", periods=130)
    rows = []
    for name, base, drift in [("CSI300", 4000.0, 0.0008), ("CSI500", 6000.0, 0.0006)]:
        for index, date in enumerate(dates):
            rows.append(
                {
                    "index": name,
                    "date": date.date().isoformat(),
                    "close": base * (1 + drift) ** index,
                    "breadth_above_ma20": 0.55,
                    "breadth_above_ma60": 0.50,
                }
            )
    pd.DataFrame(rows).to_csv(csv_path, index=False)

    report = build_market_index_discovery_report(
        search_dirs=[tmp_path / "indices"],
        output_dir=tmp_path / "out",
        as_of=dates[-1].date().isoformat(),
    )
    candidate = report.candidates[0]

    assert report.status == "PASS"
    assert report.best_candidate == str(csv_path)
    assert candidate.index_count == 2
    assert candidate.index_names == ["CSI300", "CSI500"]
    assert "write_market_context_snapshot.py" in candidate.snapshot_command
    assert "--index-csv" in report.next_commands[0]


def test_market_index_discovery_ignores_contract_index_constituents(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    data_dir.mkdir()
    (data_dir / "index_constituents.csv").write_text(
        "date,index_code,symbol\n2026-06-10,000300,000001\n",
        encoding="utf-8",
    )

    report = build_market_index_discovery_report(
        search_dirs=[data_dir],
        output_dir=tmp_path / "out",
        as_of="2026-06-10",
    )

    assert report.status == "BLOCK"
    assert report.candidates[0].path == str(data_dir)
    assert "No candidate index CSV files" in report.candidates[0].findings[0]


def test_market_index_discovery_cli_writes_outputs(tmp_path: Path) -> None:
    csv_path = tmp_path / "csi300_index.csv"
    dates = pd.bdate_range("2026-01-01", periods=80)
    pd.DataFrame(
        {
            "date": [date.date().isoformat() for date in dates],
            "close": [4000.0 * (1.0005**index) for index, _date in enumerate(dates)],
        }
    ).to_csv(csv_path, index=False)
    out = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_market_index_discovery.py",
            "--search-dir",
            str(csv_path),
            "--output-dir",
            str(out),
            "--as-of",
            dates[-1].date().isoformat(),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((out / "market_index_discovery.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["status"] == "PASS"
    assert payload["candidates"][0]["index_names"] == ["csi300_index"]
    assert (out / "market_index_discovery.md").exists()
