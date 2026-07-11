from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from quantify.data.provider_smoke_readiness import (
    build_provider_smoke_readiness,
    write_provider_smoke_readiness,
)


def test_provider_smoke_readiness_passes_endpoint_but_watches_small_sample(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "data_import.json"
    _write_import_report(
        report_path,
        {
            "status": "PASS",
            "start": "2024-06-03",
            "end": "2026-06-05",
            "requested_symbols": 2,
            "imported_symbols": 2,
            "failed_symbols": 0,
            "bar_rows": 974,
            "calendar_days": 487,
            "failures": [],
            "metadata": {
                "actual_bar_start": "2024-06-03",
                "actual_bar_end": "2026-06-05",
                "actual_bar_symbol_count": 2,
            },
        },
    )

    report = build_provider_smoke_readiness(
        latest_import_report_path=report_path,
        requested_end="2026-06-05",
        as_of="2026-06-12",
        min_symbols=300,
        min_trading_days=240,
    )
    out = write_provider_smoke_readiness(report, tmp_path / "out")
    payload = json.loads((out / "provider_smoke_readiness.json").read_text(encoding="utf-8"))
    markdown = (out / "provider_smoke_readiness.md").read_text(encoding="utf-8")

    assert report.status == "WATCH"
    assert report.endpoint_viability == "PASS"
    assert report.data_sufficiency_status == "WATCH"
    assert report.imported_symbols == 2
    assert any("not sufficient for broad research" in item for item in report.watch_items)
    assert payload["latest_import_report_path"] == str(report_path)
    assert "cannot approve source QA" in markdown


def test_provider_smoke_readiness_blocks_network_failure(tmp_path: Path) -> None:
    report_path = tmp_path / "data_import.json"
    _write_import_report(
        report_path,
        {
            "status": "BLOCK",
            "start": "2024-06-03",
            "end": "2026-06-05",
            "requested_symbols": 2,
            "imported_symbols": 0,
            "failed_symbols": 2,
            "bar_rows": 0,
            "calendar_days": 0,
            "network_blocked": True,
            "failure_stage": "symbol_list",
            "recommended_route": "offline_csv_or_tdx",
            "failures": [{"symbol": "symbol_list", "reason": "ProxyError: Unable to connect to proxy"}],
            "metadata": {
                "actual_bar_start": "",
                "actual_bar_end": "",
                "actual_bar_symbol_count": 0,
            },
        },
    )

    report = build_provider_smoke_readiness(
        latest_import_report_path=report_path,
        requested_end="2026-06-05",
        as_of="2026-06-12",
    )

    assert report.status == "BLOCK"
    assert report.endpoint_viability == "BLOCK"
    assert report.network_blocked is True
    assert report.recommended_route == "offline_csv_or_tdx"
    assert "network/proxy blocked" in report.blockers[0]
    assert "offline CSV/TDX" in report.next_actions[0]


def test_provider_smoke_readiness_missing_report_is_watch_not_block(tmp_path: Path) -> None:
    report = build_provider_smoke_readiness(
        latest_import_report_path=tmp_path / "missing.json",
        requested_end="2026-06-05",
        as_of="2026-06-12",
    )

    assert report.status == "WATCH"
    assert report.attempted is False
    assert report.endpoint_viability == "WATCH"
    assert report.data_sufficiency_status == "BLOCK"
    assert "missing or unreadable" in report.watch_items[0]


def test_provider_smoke_readiness_cli_writes_report(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    import_report = tmp_path / "data_import.json"
    out = tmp_path / "out"
    _write_config(config, tmp_path / "recent.db")
    _write_import_report(
        import_report,
        {
            "status": "PASS",
            "start": "2024-01-02",
            "end": "2024-01-03",
            "requested_symbols": 2,
            "imported_symbols": 2,
            "failed_symbols": 0,
            "bar_rows": 4,
            "calendar_days": 2,
            "failures": [],
            "metadata": {
                "actual_bar_start": "2024-01-02",
                "actual_bar_end": "2024-01-03",
                "actual_bar_symbol_count": 2,
            },
        },
    )

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_provider_smoke_readiness.py",
            "--config",
            str(config),
            "--latest-import-report",
            str(import_report),
            "--output-dir",
            str(out),
            "--as-of",
            "2024-01-03",
            "--min-symbols",
            "2",
            "--min-trading-days",
            "2",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((out / "provider_smoke_readiness.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["status"] == "PASS"
    assert payload["endpoint_viability"] == "PASS"
    assert payload["data_sufficiency_status"] == "PASS"


def _write_import_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_config(path: Path, cache: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "research:",
                '  start: "2024-01-02"',
                '  end: "2024-01-03"',
                "  allow_demo_data: false",
                "data:",
                f"  cache_path: '{cache}'",
                "  source: akshare",
                "  adjust: qfq",
                "universe:",
                "  index_code: '000906'",
                "  mode: all_a",
                "  include_st: false",
                "  min_history_days: 1",
                "strategy:",
                "  n_holdings: 2",
                "  max_weight: 0.10",
                "risk:",
                "  max_drawdown_stop: 0.2",
                "broker:",
                "  commission_rate: 0.0",
                "  min_commission: 0.0",
                "  stamp_tax: 0.0",
                "  slippage_bps: 0.0",
                "  price_limit_pct: 0.10",
                "  lot_size: 100",
            ]
        ),
        encoding="utf-8",
    )
