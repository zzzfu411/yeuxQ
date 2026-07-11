from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.csv_contract import write_research_csv_templates
from quantify.data.real_data_handoff import (
    build_real_data_handoff_checklist,
    write_real_data_handoff_checklist,
)
from quantify.data.source_qa import (
    build_data_source_qa,
    build_data_source_qa_answers,
    write_data_source_qa,
    write_data_source_qa_answers,
)


def test_real_data_handoff_blocks_template_rows_and_missing_source_qa(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)

    checklist = build_real_data_handoff_checklist(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
    )
    out = write_real_data_handoff_checklist(checklist, tmp_path / "out")

    payload = json.loads((out / "real_data_handoff_checklist.json").read_text(encoding="utf-8"))
    paths = {item["name"]: item for item in payload["evidence_paths"]}
    files = {item["role"]: item for item in payload["file_requirements"]}
    markdown = (out / "real_data_handoff_checklist.md").read_text(encoding="utf-8")

    assert payload["status"] == "BLOCK"
    assert paths["ohlcv_minimum_path"]["status"] == "BLOCK"
    assert files["bars"]["state"] == "template_sample_rows"
    assert files["bars"]["preview_status"] == "PASS"
    assert "symbol" in files["bars"]["mapped_columns"]
    assert files["bars"]["missing_columns"] == []
    assert any("data_source_qa_answers.json" in item for item in payload["next_actions"])
    assert any(item["name"] == "write_tdx_source_qa_answers" for item in payload["commands"])
    assert "not a strategy recommendation" in markdown
    assert "price_volume_defensive" in markdown


def test_real_data_handoff_blocks_unmappable_bars_columns(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    write_research_csv_templates(data_dir)
    (data_dir / "bars.csv").write_text(
        "\n".join(
            [
                "symbol,date,open,high,low,volume,amount",
                "000010,2024-01-02,10,11,9,1000,10000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _write_config(config, cache)
    _write_source_qa_answers(data_dir, config)

    checklist = build_real_data_handoff_checklist(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
    )

    paths = {item.name: item for item in checklist.evidence_paths}
    files = {item.role: item for item in checklist.file_requirements}
    assert checklist.status == "BLOCK"
    assert files["bars"].preview_status == "BLOCK"
    assert files["bars"].missing_columns == ["close"]
    assert paths["ohlcv_minimum_path"].status == "BLOCK"
    assert any("bars.csv preview is BLOCK" in item for item in paths["ohlcv_minimum_path"].blocked_by)


def test_real_data_handoff_watches_ohlcv_only_export_without_fundamentals(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    _write_bars_only_export(data_dir)
    _write_config(config, cache)
    _write_source_qa_answers(data_dir, config)

    checklist = build_real_data_handoff_checklist(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
    )

    paths = {item.name: item for item in checklist.evidence_paths}
    files = {item.role: item for item in checklist.file_requirements}
    assert checklist.status == "WATCH"
    assert paths["ohlcv_minimum_path"].status == "WATCH"
    assert paths["pit_fundamental_candidate_path"].status == "BLOCK"
    assert files["bars"].state == "present"
    assert files["fundamentals"].state == "missing"
    assert "price_volume_defensive" in paths["ohlcv_minimum_path"].candidate_scope
    assert any("fundamental-dependent candidates" in item for item in checklist.next_actions)


def test_real_data_handoff_passes_complete_replaced_export(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    _write_full_export(data_dir)
    _write_config(config, cache)
    _write_source_qa_answers(data_dir, config)

    checklist = build_real_data_handoff_checklist(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
    )

    paths = {item.name: item for item in checklist.evidence_paths}
    assert checklist.status == "PASS"
    assert paths["ohlcv_minimum_path"].status == "PASS"
    assert paths["pit_fundamental_candidate_path"].status == "PASS"


def test_real_data_handoff_cli_writes_block_report(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    output = tmp_path / "out"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_real_data_handoff.py",
            "--data-dir",
            str(data_dir),
            "--config",
            str(config),
            "--output-dir",
            str(output),
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

    payload = json.loads((output / "real_data_handoff_checklist.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["status"] == "BLOCK"
    assert any(item["name"] == "ohlcv_minimum_path" for item in payload["evidence_paths"])


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
                "output:",
                f"  results_dir: '{path.parent / 'results'}'",
            ]
        ),
        encoding="utf-8",
    )


def _write_source_qa_answers(data_dir: Path, config: Path) -> None:
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
        point_in_time_evidence="PIT snapshots where provided; missing fundamentals keep dependent candidates downgraded",
        reviewed_by="tester",
        reviewed_at="2024-01-03",
    )
    write_data_source_qa_answers(answers, data_dir / "data_source_qa_answers.json")


def _write_bars_only_export(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    _bars().to_csv(data_dir / "bars.csv", index=False)


def _write_full_export(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    _bars().to_csv(data_dir / "bars.csv", index=False)
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


def _bars() -> pd.DataFrame:
    return pd.DataFrame(
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
    )
