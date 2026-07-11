from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.ohlcv_intake_closeout import run_ohlcv_intake_closeout
from quantify.data.source_qa import (
    build_data_source_qa,
    build_source_qa_evidence_manifest,
    write_data_source_qa,
    write_source_qa_evidence_manifest,
)
from quantify.data.storage import BarStorage


def test_ohlcv_intake_closeout_blocks_source_qa_before_normalization(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    raw_bars = data_dir / "raw" / "raw_vendor_bars.csv"
    _write_config(config, cache)
    _write_raw_bars(raw_bars)

    closeout = run_ohlcv_intake_closeout(
        data_dir=data_dir,
        report_dir=report_dir,
        config_path=config,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
    )

    payload = json.loads((report_dir / "ohlcv_intake_closeout.json").read_text(encoding="utf-8"))
    assert closeout.decision == "BLOCK"
    assert payload["offline_intake_status"] == "NOT_RUN"
    assert any("source_qa" in item for item in payload["blockers"])
    assert not (data_dir / "bars.csv").exists()
    assert not cache.exists()


def test_ohlcv_intake_closeout_runs_guarded_intake_from_discovered_raw_bars(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    raw_bars = data_dir / "raw" / "raw_vendor_bars.csv"
    _write_config(config, cache)
    _write_raw_bars(raw_bars)
    _write_optional_metadata(data_dir)
    _write_source_qa_bundle(data_dir, config)

    closeout = run_ohlcv_intake_closeout(
        data_dir=data_dir,
        report_dir=report_dir,
        config_path=config,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
    )

    payload = json.loads((report_dir / "ohlcv_intake_closeout.json").read_text(encoding="utf-8"))
    metadata = BarStorage(cache).load_metadata()
    assert closeout.decision == "PASS"
    assert payload["raw_bars_csv"] == str(raw_bars)
    assert payload["raw_sha256"] == _sha256(raw_bars)
    assert payload["offline_intake_status"] == "PASS"
    assert payload["csv_dataset_fingerprint"]
    assert metadata["raw_vendor_bars_sha256"] == _sha256(raw_bars)
    assert metadata["csv_dataset_fingerprint"] == payload["csv_dataset_fingerprint"]
    assert payload["latest_bar_date"] == "2024-01-03"
    assert (data_dir / "bars.csv").exists()
    assert (report_dir / "offline_intake" / "data_import.json").exists()
    assert (report_dir / "ohlcv_intake_closeout.csv").exists()


def test_ohlcv_intake_closeout_cli_returns_nonzero_on_block(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    raw_bars = data_dir / "raw" / "raw_vendor_bars.csv"
    _write_config(config, cache)
    _write_raw_bars(raw_bars)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_ohlcv_intake_closeout.py",
            "--data-dir",
            str(data_dir),
            "--report-dir",
            str(report_dir),
            "--config",
            str(config),
            "--min-symbols",
            "2",
            "--min-trading-days",
            "2",
            "--as-of",
            "2024-01-03",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((report_dir / "ohlcv_intake_closeout.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"


def _write_config(path: Path, cache: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "research:",
                '  start: "2024-01-02"',
                '  end: "2024-01-03"',
                '  in_sample_end: "2024-01-02"',
                '  out_sample_start: "2024-01-03"',
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
                "  name: price_volume_defensive",
                "  n_holdings: 2",
                "  max_weight: 0.10",
                "risk:",
                "  max_drawdown_stop: 0.2",
                "broker:",
                "  commission_rate: 0.0",
                "  stamp_tax: 0.0",
                "  slippage_bps: 0.0",
                "  price_limit_pct: 0.10",
                "  lot_size: 100",
            ]
        ),
        encoding="utf-8",
    )


def _write_raw_bars(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _bars().to_csv(path, index=False)


def _write_optional_metadata(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "symbol": ["600111", "000222"],
            "name": ["UnitSSE", "UnitSZSE"],
            "exchange": ["SSE", "SZSE"],
            "list_date": ["2001-01-01", "2002-01-01"],
            "delist_date": ["", ""],
            "industry": ["industry_a", "industry_b"],
            "is_st": [0, 0],
        }
    ).to_csv(data_dir / "stock_info.csv", index=False)
    pd.DataFrame(
        {
            "symbol": ["600111", "000222"],
            "date": ["2024-01-02", "2024-01-02"],
            "pe_ttm": [12.0, 18.0],
            "pb": [1.2, 1.8],
            "roe": [0.10, 0.12],
            "market_cap": [19_000_000_000, 23_000_000_000],
            "turnover_rate": [0.018, 0.028],
        }
    ).to_csv(data_dir / "fundamentals.csv", index=False)
    pd.DataFrame({"date": ["2024-01-02", "2024-01-03", "2024-01-04"], "is_open": [1, 1, 0]}).to_csv(
        data_dir / "calendar.csv",
        index=False,
    )
    pd.DataFrame(
        {
            "symbol": ["600111", "000222"],
            "date": ["2024-01-03", "2024-01-03"],
            "is_suspended": [0, 0],
        }
    ).to_csv(data_dir / "suspensions.csv", index=False)
    pd.DataFrame(
        {
            "index_code": ["000906", "000906"],
            "date": ["2024-01-02", "2024-01-02"],
            "symbol": ["600111", "000222"],
        }
    ).to_csv(data_dir / "index_constituents.csv", index=False)


def _write_source_qa_bundle(data_dir: Path, config: Path) -> None:
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=2,
        as_of="2024-01-03",
    )
    write_data_source_qa(checklist, data_dir)
    _write_source_answers(data_dir / "data_source_qa_answers.json", checklist.to_dict())
    evidence_dir = data_dir / "source_qa_evidence"
    for item in checklist.checklist:
        if item.review_stage == "source" and item.severity == "BLOCK_IF_NO":
            _write_evidence_file(evidence_dir / f"{item.id}_evidence.txt", item.id)
    manifest = build_source_qa_evidence_manifest(
        checklist_path=data_dir / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, data_dir)


def _bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["600111", "600111", "000222", "000222"],
            "date": ["2024-01-02", "2024-01-03", "2024-01-02", "2024-01-03"],
            "open": [13.0, 13.4, 27.0, 27.4],
            "high": [13.8, 13.9, 27.8, 27.9],
            "low": [12.7, 13.0, 26.7, 27.0],
            "close": [13.5, 13.6, 27.5, 27.6],
            "volume": [3_500_000, 3_600_000, 4_500_000, 4_600_000],
            "amount": [47_250_000, 48_960_000, 123_750_000, 126_960_000],
        }
    )


def _write_source_answers(path: Path, checklist: dict) -> None:
    answers = {
        item["id"]: {
            "answer": "yes",
            "evidence": f"source evidence for {item['id']}",
            "notes": "",
        }
        for item in checklist["checklist"]
        if item["review_stage"] == "source"
    }
    payload = {
        "source_metadata": {
            "data_vendor_or_broker": "unit-test vendor",
            "terminal_or_product_name": "unit-test terminal",
            "export_operator": "tester",
            "exported_at_local_time": "2024-01-03 18:00:00",
            "market": "A-share equities",
            "frequency": "daily",
            "date_range": "2024-01-02 to 2024-01-03",
            "price_adjustment": "qfq",
            "encoding": "utf-8-sig",
            "license_or_usage_scope": "research and paper trading only",
            "known_limitations": "none",
            "reviewed_by": "tester",
            "reviewed_at": "2024-01-03",
        },
        "answers": answers,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_evidence_file(path: Path, item_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"auditable local evidence for {item_id}", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
