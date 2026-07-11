from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.csv_contract import write_research_csv_templates
from quantify.data.offline_package import (
    build_offline_data_package_report,
    write_offline_data_package_report,
)
from quantify.data.source_qa import (
    build_data_source_qa,
    build_data_source_qa_answers,
    build_source_qa_evidence_manifest,
    write_data_source_qa,
    write_data_source_qa_answers,
    write_source_qa_evidence_manifest,
)


def test_offline_data_package_blocks_missing_answers_and_template_rows(tmp_path: Path) -> None:
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

    report = build_offline_data_package_report(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        as_of="2024-01-03",
    )
    out = write_offline_data_package_report(report, tmp_path / "out")

    payload = json.loads((out / "offline_data_package.json").read_text(encoding="utf-8"))
    item_status = {item["name"]: item["status"] for item in payload["items"]}
    markdown = (out / "offline_data_package.md").read_text(encoding="utf-8")

    assert payload["status"] == "BLOCK"
    assert item_status["source_qa_answers"] == "BLOCK"
    assert item_status["source_qa_review"] == "BLOCK"
    assert item_status["source_qa_evidence_manifest"] == "PASS"
    assert item_status["csv_template_rows"] == "BLOCK"
    assert "Fill data_source_qa_answers.json" in "\n".join(payload["next_actions"])
    assert "not a strategy recommendation" in markdown


def test_offline_data_package_passes_complete_replaced_export_and_source_qa(
    tmp_path: Path,
) -> None:
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

    report = build_offline_data_package_report(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        as_of="2024-01-03",
    )

    item_status = {item.name: item.status for item in report.items}
    assert report.status == "PASS"
    assert item_status["source_qa_review"] == "PASS"
    assert item_status["source_qa_evidence_manifest"] == "PASS"
    assert item_status["csv_inventory"] == "PASS"
    assert item_status["csv_template_rows"] == "PASS"
    assert item_status["import_doctor"] == "PASS"
    assert report.csv_files
    assert report.source_metadata_summary["source_identity"] == "unit-test vendor / unit-test terminal"
    assert report.source_metadata_summary["exported_at_local_time"] == "2024-01-03 18:00:00"
    assert report.source_metadata_summary["price_adjustment"] == "qfq"
    assert report.source_metadata_summary["human_review"] == "tester at 2024-01-03"
    assert report.source_metadata_summary["price_adjustment_evidence"] == "vendor export setting says qfq"


def test_offline_data_package_strict_manifest_blocks_missing_attachments(
    tmp_path: Path,
) -> None:
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

    report = build_offline_data_package_report(
        data_dir=data_dir,
        config_path=config,
        source_qa_evidence_manifest=data_dir / "source_qa_evidence_manifest.json",
        require_source_qa_evidence_manifest=True,
        min_symbols=2,
        as_of="2024-01-03",
    )
    out = write_offline_data_package_report(report, tmp_path / "out")

    payload = json.loads((out / "offline_data_package.json").read_text(encoding="utf-8"))
    item_status = {item["name"]: item["status"] for item in payload["items"]}
    item_by_name = {item["name"]: item for item in payload["items"]}
    markdown = (out / "offline_data_package.md").read_text(encoding="utf-8")
    assert report.status == "BLOCK"
    assert item_status["source_qa_review"] == "BLOCK"
    assert item_status["source_qa_evidence_manifest"] == "BLOCK"
    assert "SOURCE_QA_EVIDENCE_MANIFEST_MISSING" in item_by_name["source_qa_evidence_manifest"]["message"]
    assert payload["require_source_qa_evidence_manifest"] is True
    assert payload["source_qa_evidence_manifest_path"].endswith("source_qa_evidence_manifest.json")
    assert any("source_qa_evidence_manifest.json" in action for action in payload["next_actions"])
    assert any("--require-source-qa-evidence-manifest" in command for command in payload["next_commands"])
    assert "Require source QA evidence manifest: `True`" in markdown


def test_offline_data_package_strict_manifest_passes_with_attachments(
    tmp_path: Path,
) -> None:
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
    _write_required_source_qa_attachments(data_dir, checklist.to_dict())

    report = build_offline_data_package_report(
        data_dir=data_dir,
        config_path=config,
        source_qa_evidence_manifest=data_dir / "source_qa_evidence_manifest.json",
        require_source_qa_evidence_manifest=True,
        min_symbols=2,
        as_of="2024-01-03",
    )

    item_status = {item.name: item.status for item in report.items}
    assert report.status == "PASS"
    assert item_status["source_qa_review"] == "PASS"
    assert item_status["source_qa_evidence_manifest"] == "PASS"
    assert report.require_source_qa_evidence_manifest is True
    assert report.source_qa_evidence_manifest_path.endswith("source_qa_evidence_manifest.json")


def test_offline_data_package_markdown_surfaces_human_source_provenance(
    tmp_path: Path,
) -> None:
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

    report = build_offline_data_package_report(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        as_of="2024-01-03",
    )
    out = write_offline_data_package_report(report, tmp_path / "out")

    payload = json.loads((out / "offline_data_package.json").read_text(encoding="utf-8"))
    markdown = (out / "offline_data_package.md").read_text(encoding="utf-8")
    assert payload["source_metadata_summary"]["data_vendor_or_broker"] == "unit-test vendor"
    assert payload["source_metadata_summary"]["terminal_or_product_name"] == "unit-test terminal"
    assert payload["source_metadata_summary"]["manual_signoff_evidence"] == (
        "reviewed_by=tester; reviewed_at=2024-01-03"
    )
    assert "`source_identity`: `unit-test vendor / unit-test terminal`" in markdown
    assert "`exported_at_local_time`: `2024-01-03 18:00:00`" in markdown
    assert "`human_review`: `tester at 2024-01-03`" in markdown


def test_offline_data_package_cli_writes_block_report(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    output = tmp_path / "out"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_offline_data_package.py",
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

    payload = json.loads((output / "offline_data_package.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["status"] == "BLOCK"
    assert any(item["name"] == "source_qa_checklist" for item in payload["items"])


def test_offline_data_package_cli_requires_evidence_manifest(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    output = tmp_path / "out"
    _write_replaced_export(data_dir)
    _write_config(config, cache)
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

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_offline_data_package.py",
            "--data-dir",
            str(data_dir),
            "--config",
            str(config),
            "--output-dir",
            str(output),
            "--source-qa-answers",
            str(data_dir / "data_source_qa_answers.json"),
            "--source-qa-evidence-manifest",
            str(data_dir / "source_qa_evidence_manifest.json"),
            "--require-source-qa-evidence-manifest",
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

    payload = json.loads((output / "offline_data_package.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["status"] == "BLOCK"
    assert payload["require_source_qa_evidence_manifest"] is True
    assert any(item["name"] == "source_qa_review" and item["status"] == "BLOCK" for item in payload["items"])


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
