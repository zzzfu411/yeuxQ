from __future__ import annotations

import json
from pathlib import Path
import struct
import subprocess
import sys

import pandas as pd

from quantify.data.csv_contract import write_research_csv_templates
from quantify.data.gap_action_plan import build_data_gap_action_plan, write_data_gap_action_plan
from quantify.data.source_qa import build_data_source_qa, write_data_source_qa
from quantify.data.tdx_day import export_tdx_day_to_csv


def test_data_gap_action_plan_blocks_missing_answers_and_templates(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=2,
        as_of="2024-01-03",
    )
    write_data_source_qa(checklist, data_dir)

    plan = build_data_gap_action_plan(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        as_of="2024-01-03",
    )
    out = write_data_gap_action_plan(plan, tmp_path / "out")

    payload = json.loads((out / "data_gap_action_plan.json").read_text(encoding="utf-8"))
    item_status = {item["name"]: item["status"] for item in payload["items"]}

    assert payload["decision"] == "BLOCK"
    assert item_status["source_qa_answers"] == "BLOCK"
    assert item_status["source_metadata"] == "BLOCK"
    assert item_status["source_qa_preflight"] == "BLOCK"
    assert item_status["source_qa_review"] == "BLOCK"
    assert item_status["csv_template_rows"] == "BLOCK"
    assert "source_qa_preflight" in {item["name"] for item in payload["items"]}
    assert "evidence worksheet" in "\n".join(payload["next_actions"])
    assert "write_data_source_qa_evidence_worksheet.py" in "\n".join(payload["next_commands"])
    assert "write_data_source_qa_answers.py" in "\n".join(payload["next_commands"])
    assert "--require-evidence-manifest" in "\n".join(payload["next_commands"])
    assert "run_source_qa_preflight.py" in "\n".join(payload["next_commands"])
    assert "run_source_qa_evidence_readiness.py" in "\n".join(payload["next_commands"])
    assert "run_csv_intake_preview.py" in "\n".join(payload["next_commands"])
    assert (out / "data_gap_action_plan.md").exists()


def test_data_gap_action_plan_passes_replaced_csv_and_complete_source_qa(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    _write_replaced_export(data_dir)
    _write_config(config, cache)
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=2,
        as_of="2024-01-03",
    )
    write_data_source_qa(checklist, data_dir)
    _write_source_answers(data_dir / "data_source_qa_answers.json", checklist.to_dict())

    plan = build_data_gap_action_plan(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        as_of="2024-01-03",
    )

    item_status = {item.name: item.status for item in plan.items}
    assert plan.decision == "PASS"
    assert item_status["source_qa_answers"] == "PASS"
    assert item_status["source_metadata"] == "PASS"
    assert item_status["source_qa_preflight"] == "PASS"
    assert item_status["source_qa_review"] == "PASS"
    assert item_status["csv_template_rows"] == "PASS"
    assert item_status["import_doctor"] == "PASS"


def test_data_gap_action_plan_blocks_placeholder_source_metadata(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    _write_replaced_export(data_dir)
    _write_config(config, cache)
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=2,
        as_of="2024-01-03",
    )
    write_data_source_qa(checklist, data_dir)
    _write_placeholder_source_answers(data_dir / "data_source_qa_answers.json", checklist.to_dict())

    plan = build_data_gap_action_plan(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        as_of="2024-01-03",
    )

    item_status = {item.name: item.status for item in plan.items}
    item_messages = {item.name: item.message for item in plan.items}
    assert plan.decision == "BLOCK"
    assert item_status["source_qa_answers"] == "PASS"
    assert item_status["source_metadata"] == "BLOCK"
    assert item_status["source_qa_preflight"] == "BLOCK"
    assert item_status["source_qa_review"] == "BLOCK"
    assert "placeholder" in item_messages["source_metadata"].lower()
    assert "data_vendor_or_broker" in item_messages["source_qa_preflight"]


def test_data_gap_action_plan_surfaces_tdx_specific_next_commands(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    tdx_root = tmp_path / "vipdoc"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    _write_config(config, cache)
    _write_day_file(tdx_root / "sh" / "lday" / "sh600010.day", symbol_base=10.0)
    _write_day_file(tdx_root / "sz" / "lday" / "sz000010.day", symbol_base=20.0)
    export_tdx_day_to_csv(
        input_dir=tdx_root,
        output_dir=data_dir,
        start="2024-01-02",
        end="2024-01-03",
    )
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=2,
        as_of="2024-01-03",
    )
    write_data_source_qa(checklist, data_dir)

    plan = build_data_gap_action_plan(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        as_of="2024-01-03",
    )

    item_status = {item.name: item.status for item in plan.items}
    item_messages = {item.name: item.message for item in plan.items}
    commands = "\n".join(plan.next_commands)
    actions = "\n".join(plan.next_actions)
    assert plan.decision == "BLOCK"
    assert item_status["tdx_day_export"] == "PASS"
    assert "symbols=2" in item_messages["tdx_day_export"]
    assert "write_data_source_qa_evidence_worksheet.py" in commands
    assert "write_tdx_source_qa_answers.py" in commands
    assert "run_source_qa_preflight.py" in commands
    assert "--tdx-input-dir <tdx-vipdoc-or-lday-dir>" in commands
    assert "OHLCV-only" in actions


def test_data_gap_action_plan_cli_writes_block_report(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    output = tmp_path / "out"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_data_gap_action_plan.py",
            "--data-dir",
            str(data_dir),
            "--config",
            str(config),
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

    payload = json.loads((output / "data_gap_action_plan.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"
    assert any(item["name"] == "source_qa_answers" for item in payload["items"])


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


def _write_placeholder_source_answers(path: Path, checklist: dict) -> None:
    answers = {
        item["id"]: {
            "answer": "yes",
            "evidence": "<evidence>",
            "notes": "",
        }
        for item in checklist["checklist"]
        if item["review_stage"] == "source"
    }
    payload = {
        "source_metadata": {
            "data_vendor_or_broker": "<vendor-or-broker>",
            "terminal_or_product_name": "<terminal-name>",
            "export_operator": "<operator>",
            "exported_at_local_time": "<local-time>",
            "market": "A-share equities",
            "frequency": "daily",
            "date_range": "2024-01-02 to 2024-01-03",
            "price_adjustment": "qfq",
            "encoding": "utf-8-sig",
            "license_or_usage_scope": "research and paper trading only",
            "known_limitations": "",
            "reviewed_by": "<name>",
            "reviewed_at": "<date>",
        },
        "answers": answers,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
