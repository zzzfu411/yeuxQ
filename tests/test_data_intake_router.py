from __future__ import annotations

import json
from pathlib import Path
import struct
import subprocess
import sys

import pandas as pd

from quantify.data.csv_contract import write_research_csv_templates
from quantify.data.intake_router import build_data_intake_router, write_data_intake_router
from quantify.data.source_qa import (
    build_data_source_qa,
    build_data_source_qa_answers,
    build_source_qa_evidence_manifest,
    write_data_source_qa,
    write_data_source_qa_answers,
    write_source_qa_evidence_manifest,
)


def test_data_intake_router_recommends_offline_csv_when_provider_and_tdx_block(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    import_report = tmp_path / "data_import.json"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)
    _write_network_blocked_import_report(import_report)

    report = build_data_intake_router(
        data_dir=data_dir,
        config_path=config,
        latest_import_report_path=import_report,
        tdx_search_dirs=[tmp_path / "missing_tdx"],
        min_symbols=2,
        as_of="2024-01-03",
    )
    out = write_data_intake_router(report, tmp_path / "out")

    payload = json.loads((out / "data_intake_router.json").read_text(encoding="utf-8"))
    routes = {route["name"]: route for route in payload["routes"]}
    markdown = (out / "data_intake_router.md").read_text(encoding="utf-8")
    assert payload["status"] == "BLOCK"
    assert payload["recommended_route"] == "broker_vendor_csv"
    assert routes["provider_akshare"]["status"] == "BLOCK"
    assert routes["tdx_ohlcv"]["status"] == "BLOCK"
    assert routes["broker_vendor_csv"]["status"] == "BLOCK"
    assert "not a strategy approval" in markdown


def test_data_intake_router_prefers_discovered_tdx_ohlcv_path(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    import_report = tmp_path / "data_import.json"
    tdx_root = tmp_path / "vipdoc"
    _write_config(config, cache)
    _write_network_blocked_import_report(import_report)
    _write_day_file(tdx_root / "sh" / "lday" / "sh600010.day", symbol_base=10.0)
    _write_day_file(tdx_root / "sz" / "lday" / "sz000010.day", symbol_base=20.0)

    report = build_data_intake_router(
        data_dir=data_dir,
        config_path=config,
        latest_import_report_path=import_report,
        tdx_search_dirs=[tdx_root],
        min_symbols=2,
        as_of="2024-01-03",
    )

    route = report.route("tdx_ohlcv")
    assert report.status == "PASS"
    assert report.recommended_route == "tdx_ohlcv"
    assert route is not None
    assert route.status == "PASS"
    assert route.candidate_scope == ["OHLCV-only candidate family"]
    assert any("run_tdx_ohlcv_intake.py" in command for command in route.commands)


def test_data_intake_router_passes_broker_vendor_csv_package(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    _write_config(config, cache)
    _write_replaced_export(data_dir)
    _write_source_qa_answers(data_dir, config)

    report = build_data_intake_router(
        data_dir=data_dir,
        config_path=config,
        latest_import_report_path=tmp_path / "missing_import.json",
        tdx_search_dirs=[tmp_path / "missing_tdx"],
        min_symbols=2,
        as_of="2024-01-03",
    )

    route = report.route("broker_vendor_csv")
    assert report.status == "PASS"
    assert report.recommended_route == "broker_vendor_csv"
    assert route is not None
    assert route.status == "PASS"
    assert any("normalize_vendor_bars.py" in command for command in route.commands)
    assert any("run_offline_data_intake.py" in command for command in route.commands)


def test_data_intake_router_strict_manifest_blocks_broker_vendor_csv_package(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    _write_config(config, cache)
    _write_replaced_export(data_dir)
    _write_source_qa_answers(data_dir, config)

    report = build_data_intake_router(
        data_dir=data_dir,
        config_path=config,
        source_qa_evidence_manifest=data_dir / "source_qa_evidence_manifest.json",
        require_source_qa_evidence_manifest=True,
        latest_import_report_path=tmp_path / "missing_import.json",
        tdx_search_dirs=[tmp_path / "missing_tdx"],
        min_symbols=2,
        as_of="2024-01-03",
    )

    route = report.route("broker_vendor_csv")
    assert report.status == "WATCH"
    assert report.recommended_route == "provider_akshare"
    assert route is not None
    assert route.status == "BLOCK"
    assert any("source_qa_evidence_manifest" in blocker for blocker in route.blockers)


def test_data_intake_router_strict_manifest_passes_with_attachments(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    _write_config(config, cache)
    _write_replaced_export(data_dir)
    checklist = _write_source_qa_answers(data_dir, config)
    _write_required_source_qa_attachments(data_dir, checklist)

    report = build_data_intake_router(
        data_dir=data_dir,
        config_path=config,
        source_qa_evidence_manifest=data_dir / "source_qa_evidence_manifest.json",
        require_source_qa_evidence_manifest=True,
        latest_import_report_path=tmp_path / "missing_import.json",
        tdx_search_dirs=[tmp_path / "missing_tdx"],
        min_symbols=2,
        as_of="2024-01-03",
    )

    route = report.route("broker_vendor_csv")
    assert report.status == "PASS"
    assert report.recommended_route == "broker_vendor_csv"
    assert route is not None
    assert route.status == "PASS"


def test_data_intake_router_cli_writes_block_report(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "out"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    import_report = tmp_path / "data_import.json"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)
    _write_network_blocked_import_report(import_report)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_data_intake_router.py",
            "--data-dir",
            str(data_dir),
            "--config",
            str(config),
            "--latest-import-report",
            str(import_report),
            "--tdx-search-dir",
            str(tmp_path / "missing_tdx"),
            "--output-dir",
            str(output),
            "--min-symbols",
            "2",
            "--as-of",
            "2024-01-03",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output / "data_intake_router.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["status"] == "BLOCK"
    assert payload["recommended_route"] == "broker_vendor_csv"


def _write_config(path: Path, cache: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "research:",
                '  start: "2024-01-02"',
                '  end: "2024-01-03"',
                '  in_sample_end: "2024-01-02"',
                '  out_sample_start: "2024-01-03"',
                "  initial_cash: 1000000.0",
                "  rebalance: monthly",
                "  allow_demo_data: false",
                "data:",
                "  source: csv",
                f"  cache_path: '{cache}'",
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


def _write_network_blocked_import_report(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "status": "BLOCK",
                "start": "2024-01-02",
                "end": "2024-01-03",
                "requested_symbols": 2,
                "imported_symbols": 0,
                "failed_symbols": 2,
                "bar_rows": 0,
                "calendar_days": 0,
                "failures": [
                    {
                        "symbol": "000001",
                        "reason": "ProxyError: Unable to connect to proxy",
                    }
                ],
                "metadata": {
                    "actual_bar_start": "",
                    "actual_bar_end": "",
                    "actual_bar_symbol_count": 0,
                },
            },
            ensure_ascii=False,
            indent=2,
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


def _write_source_qa_answers(data_dir: Path, config: Path) -> dict[str, object]:
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=2,
        as_of="2024-01-03",
    )
    write_data_source_qa(checklist, data_dir)
    answers = build_data_source_qa_answers(
        checklist_path=data_dir / "data_source_qa.json",
        data_vendor_or_broker="unit-test vendor",
        terminal_or_product_name="unit-test terminal",
        export_operator="tester",
        exported_at_local_time="2024-01-03 18:00:00",
        price_adjustment="qfq",
        price_adjustment_evidence="vendor export setting says qfq",
        license_or_usage_scope="research and paper trading only",
        license_evidence="unit-test license note",
        point_in_time_evidence="fundamentals and constituents are PIT snapshots",
        reviewed_by="tester",
        reviewed_at="2024-01-03",
    )
    write_data_source_qa_answers(answers, data_dir / "data_source_qa_answers.json")
    return checklist.to_dict()


def _write_replaced_export(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "symbol": ["600010", "600010", "000010", "000010"],
            "date": ["2024-01-02", "2024-01-03", "2024-01-02", "2024-01-03"],
            "open": [11.0, 11.1, 21.0, 21.1],
            "high": [11.5, 11.6, 21.5, 21.6],
            "low": [10.8, 11.0, 20.8, 21.0],
            "close": [11.2, 11.3, 21.2, 21.3],
            "volume": [1_500_000, 1_600_000, 2_500_000, 2_600_000],
            "amount": [16_800_000, 18_080_000, 53_000_000, 55_380_000],
        }
    ).to_csv(data_dir / "bars.csv", index=False)
    pd.DataFrame(
        {
            "symbol": ["600010", "000010"],
            "name": ["RealishSSE", "RealishSZSE"],
            "exchange": ["SSE", "SZSE"],
            "list_date": ["2001-01-01", "2002-01-01"],
            "delist_date": ["", ""],
            "industry": ["industry_a", "industry_b"],
            "is_st": [0, 0],
        }
    ).to_csv(data_dir / "stock_info.csv", index=False)
    pd.DataFrame(
        {
            "symbol": ["600010", "000010"],
            "date": ["2024-01-02", "2024-01-02"],
            "pe_ttm": [9.0, 11.0],
            "pb": [1.0, 1.3],
            "roe": [0.09, 0.11],
            "market_cap": [9_000_000_000, 11_000_000_000],
            "turnover_rate": [0.015, 0.025],
        }
    ).to_csv(data_dir / "fundamentals.csv", index=False)
    pd.DataFrame({"date": ["2024-01-02", "2024-01-03", "2024-01-04"], "is_open": [1, 1, 0]}).to_csv(
        data_dir / "calendar.csv",
        index=False,
    )
    pd.DataFrame(
        {
            "symbol": ["600010", "000010"],
            "date": ["2024-01-03", "2024-01-03"],
            "is_suspended": [0, 0],
        }
    ).to_csv(data_dir / "suspensions.csv", index=False)
    pd.DataFrame(
        {
            "index_code": ["000906", "000906"],
            "date": ["2024-01-02", "2024-01-02"],
            "symbol": ["600010", "000010"],
        }
    ).to_csv(data_dir / "index_constituents.csv", index=False)


def _write_required_source_qa_attachments(data_dir: Path, checklist: dict[str, object]) -> None:
    evidence_dir = data_dir / "source_qa_evidence"
    for item in checklist.get("checklist", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("review_stage") != "source" or item.get("severity") != "BLOCK_IF_NO":
            continue
        item_id = str(item.get("id", ""))
        path = evidence_dir / f"{item_id}_evidence.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"vendor export audit note for {item_id}: retained screenshot/document reviewed by tester.",
            encoding="utf-8",
        )
    manifest = build_source_qa_evidence_manifest(
        checklist_path=data_dir / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, data_dir)
