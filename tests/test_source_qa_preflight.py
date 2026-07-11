from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from quantify.data.source_qa import (
    build_data_source_qa,
    build_data_source_qa_answers,
    build_source_qa_evidence_manifest,
    write_data_source_qa,
    write_data_source_qa_answers,
    write_source_qa_evidence_manifest,
)
from quantify.data.source_qa_preflight import build_source_qa_preflight, write_source_qa_preflight


def test_source_qa_preflight_blocks_missing_answers(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    data_dir = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=300,
        as_of="2026-06-08",
    )
    write_data_source_qa(checklist, data_dir)

    report = build_source_qa_preflight(
        checklist_path=data_dir / "data_source_qa.json",
        answers_path=data_dir / "data_source_qa_answers.json",
        output_dir=tmp_path / "review",
    )
    out = write_source_qa_preflight(report, tmp_path / "review")
    payload = json.loads((out / "source_qa_preflight.json").read_text(encoding="utf-8"))

    assert report.status == "BLOCK"
    assert any(item.field == "data_source_qa_answers.json" for item in report.items)
    assert "evidence worksheet" in next(
        item.fix for item in report.items if item.field == "data_source_qa_answers.json"
    )
    assert any(item["field"] == "data_vendor_or_broker" for item in payload["items"])
    assert "write_data_source_qa_evidence_worksheet.py" in "\n".join(report.next_commands)
    assert "write_data_source_qa_answers.py" in "\n".join(report.next_commands)
    assert "--require-evidence-manifest" not in "\n".join(report.next_commands)
    assert (out / "source_qa_preflight.md").exists()


def test_source_qa_preflight_passes_complete_answers(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    data_dir = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=300,
        as_of="2026-06-08",
    )
    write_data_source_qa(checklist, data_dir)
    answers = build_data_source_qa_answers(
        checklist_path=data_dir / "data_source_qa.json",
        data_vendor_or_broker="unit-test vendor",
        terminal_or_product_name="unit-test terminal",
        export_operator="tester",
        exported_at_local_time="2026-06-08 18:00:00",
        price_adjustment="qfq",
        price_adjustment_evidence="vendor export settings show qfq",
        license_or_usage_scope="research and paper trading only",
        license_evidence="vendor account terms allow local research use",
        point_in_time_evidence="OHLCV-only export; non-PIT fundamentals excluded from candidates",
        reviewed_by="tester",
        reviewed_at="2026-06-08",
    )
    write_data_source_qa_answers(answers, data_dir / "data_source_qa_answers.json")

    report = build_source_qa_preflight(
        checklist_path=data_dir / "data_source_qa.json",
        answers_path=data_dir / "data_source_qa_answers.json",
        output_dir=tmp_path / "review",
    )

    assert report.status == "PASS"
    assert report.items == []
    assert "run_data_source_qa_review.py" in "\n".join(report.next_commands)


def test_source_qa_preflight_blocks_missing_strict_evidence_manifest(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    data_dir = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=300,
        as_of="2026-06-08",
    )
    write_data_source_qa(checklist, data_dir)
    _write_complete_answers(data_dir / "data_source_qa_answers.json", data_dir)

    report = build_source_qa_preflight(
        checklist_path=data_dir / "data_source_qa.json",
        answers_path=data_dir / "data_source_qa_answers.json",
        evidence_manifest_path=data_dir / "source_qa_evidence_manifest.json",
        require_evidence_manifest=True,
        output_dir=tmp_path / "review",
    )
    out = write_source_qa_preflight(report, tmp_path / "review")

    payload = json.loads((out / "source_qa_preflight.json").read_text(encoding="utf-8"))
    attachment = next(item for item in payload["items"] if item["kind"] == "attachment")
    assert report.status == "BLOCK"
    assert payload["evidence_manifest_path"].endswith("source_qa_evidence_manifest.json")
    assert payload["require_evidence_manifest"] is True
    assert any(item["kind"] == "evidence_manifest" for item in payload["items"])
    assert attachment["field"] == "source_identity"
    assert attachment["target"].endswith("source_identity_receipt.png")
    assert "write_source_qa_evidence_manifest.py" in attachment["next_command"]
    assert "--evidence-manifest" in "\n".join(payload["next_commands"])
    assert "--require-evidence-manifest" in "\n".join(payload["next_commands"])


def test_source_qa_preflight_passes_strict_manifest_with_retained_attachments(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    data_dir = tmp_path / "data_exports"
    evidence_dir = data_dir / "source_qa_evidence"
    _write_config(config)
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=300,
        as_of="2026-06-08",
    )
    write_data_source_qa(checklist, data_dir)
    _write_complete_answers(data_dir / "data_source_qa_answers.json", data_dir)
    for item in checklist.checklist:
        if item.review_stage == "source" and item.severity == "BLOCK_IF_NO":
            _write_evidence_file(evidence_dir / f"{item.id}_evidence.txt", item.id)
    manifest = build_source_qa_evidence_manifest(
        checklist_path=data_dir / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, data_dir)

    report = build_source_qa_preflight(
        checklist_path=data_dir / "data_source_qa.json",
        answers_path=data_dir / "data_source_qa_answers.json",
        evidence_manifest_path=data_dir / "source_qa_evidence_manifest.json",
        require_evidence_manifest=True,
        output_dir=tmp_path / "review",
    )

    assert report.status == "PASS"
    assert report.items == []
    commands = "\n".join(report.next_commands)
    assert "run_data_source_qa_review.py" in commands
    assert "--evidence-manifest" in commands
    assert "--require-evidence-manifest" in commands


def test_source_qa_preflight_blocks_strict_manifest_with_template_attachment(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    data_dir = tmp_path / "data_exports"
    evidence_dir = data_dir / "source_qa_evidence"
    _write_config(config)
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=300,
        as_of="2026-06-08",
    )
    write_data_source_qa(checklist, data_dir)
    _write_complete_answers(data_dir / "data_source_qa_answers.json", data_dir)
    for item in checklist.checklist:
        if item.review_stage == "source" and item.severity == "BLOCK_IF_NO":
            path = evidence_dir / f"{item.id}_evidence.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"retained source QA evidence for {item.id}", encoding="utf-8")
    manifest = build_source_qa_evidence_manifest(
        checklist_path=data_dir / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, data_dir)

    report = build_source_qa_preflight(
        checklist_path=data_dir / "data_source_qa.json",
        answers_path=data_dir / "data_source_qa_answers.json",
        evidence_manifest_path=data_dir / "source_qa_evidence_manifest.json",
        require_evidence_manifest=True,
        output_dir=tmp_path / "review",
    )
    payload = report.to_dict()
    placeholder_items = [
        item
        for item in payload["items"]
        if item["kind"] == "attachment" and item["field"] == "source_identity"
    ]

    assert report.status == "BLOCK"
    assert placeholder_items
    assert "PLACEHOLDER" in placeholder_items[0]["message"]
    assert "regenerate source_qa_evidence_manifest.json" in placeholder_items[0]["fix"]


def test_source_qa_preflight_blocks_strict_manifest_with_generated_attachment_path(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    data_dir = tmp_path / "data_exports"
    evidence_dir = data_dir / "source_qa_evidence"
    _write_config(config)
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=300,
        as_of="2026-06-08",
    )
    write_data_source_qa(checklist, data_dir)
    _write_complete_answers(data_dir / "data_source_qa_answers.json", data_dir)
    for item in checklist.checklist:
        if item.review_stage != "source" or item.severity != "BLOCK_IF_NO":
            continue
        file_name = "source_identity_worksheet.txt" if item.id == "source_identity" else f"{item.id}_evidence.txt"
        _write_evidence_file(evidence_dir / file_name, item.id)
    manifest = build_source_qa_evidence_manifest(
        checklist_path=data_dir / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, data_dir)

    report = build_source_qa_preflight(
        checklist_path=data_dir / "data_source_qa.json",
        answers_path=data_dir / "data_source_qa_answers.json",
        evidence_manifest_path=data_dir / "source_qa_evidence_manifest.json",
        require_evidence_manifest=True,
        output_dir=tmp_path / "review",
    )
    payload = report.to_dict()
    attachment = next(
        item
        for item in payload["items"]
        if item["kind"] == "attachment" and item["field"] == "source_identity"
    )

    assert report.status == "BLOCK"
    assert "generated workflow aid" in attachment["message"]
    assert "Replace or fix the local attachment file" in attachment["fix"]
    assert attachment["target"].endswith("source_identity_worksheet.txt")


def test_source_qa_preflight_lists_placeholder_and_weak_evidence(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    data_dir = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=300,
        as_of="2026-06-08",
    )
    write_data_source_qa(checklist, data_dir)
    answers = build_data_source_qa_answers(
        checklist_path=data_dir / "data_source_qa.json",
        data_vendor_or_broker="<vendor-or-broker>",
        terminal_or_product_name="unit-test terminal",
        export_operator="tester",
        exported_at_local_time="2026-06-08 18:00:00",
        price_adjustment="qfq",
        price_adjustment_evidence="<evidence>",
        license_or_usage_scope="research and paper trading only",
        license_evidence="sample evidence",
        point_in_time_evidence="OHLCV-only export; non-PIT fundamentals excluded from candidates",
        reviewed_by="tester",
        reviewed_at="2026-06-08",
    )
    write_data_source_qa_answers(answers, data_dir / "data_source_qa_answers.json")

    report = build_source_qa_preflight(
        checklist_path=data_dir / "data_source_qa.json",
        answers_path=data_dir / "data_source_qa_answers.json",
        output_dir=tmp_path / "review",
    )
    by_field = {(item.kind, item.field) for item in report.items}

    assert report.status == "BLOCK"
    assert ("metadata", "data_vendor_or_broker") in by_field
    assert ("evidence", "price_adjustment") in by_field
    assert ("evidence", "license_scope") in by_field


def test_source_qa_preflight_cli_writes_report_and_returns_nonzero_on_block(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    data_dir = tmp_path / "data_exports"
    review_dir = tmp_path / "review"
    _write_config(config)
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=300,
        as_of="2026-06-08",
    )
    write_data_source_qa(checklist, data_dir)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_source_qa_preflight.py",
            "--checklist",
            str(data_dir / "data_source_qa.json"),
            "--answers",
            str(data_dir / "data_source_qa_answers.json"),
            "--evidence-manifest",
            str(data_dir / "source_qa_evidence_manifest.json"),
            "--require-evidence-manifest",
            "--output-dir",
            str(review_dir),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((review_dir / "source_qa_preflight.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["status"] == "BLOCK"
    assert payload["require_evidence_manifest"] is True


def _write_complete_answers(path: Path, data_dir: Path) -> None:
    answers = build_data_source_qa_answers(
        checklist_path=data_dir / "data_source_qa.json",
        data_vendor_or_broker="unit-test vendor",
        terminal_or_product_name="unit-test terminal",
        export_operator="tester",
        exported_at_local_time="2026-06-08 18:00:00",
        price_adjustment="qfq",
        price_adjustment_evidence="vendor export settings show qfq",
        license_or_usage_scope="research and paper trading only",
        license_evidence="vendor account terms allow local research use",
        point_in_time_evidence="OHLCV-only export; non-PIT fundamentals excluded from candidates",
        reviewed_by="tester",
        reviewed_at="2026-06-08",
    )
    write_data_source_qa_answers(answers, path)


def _write_evidence_file(path: Path, item_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"vendor export audit note for {item_id}: retained screenshot/document reviewed by tester.",
        encoding="utf-8",
    )


def _write_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "research:",
                '  start: "2024-06-03"',
                '  end: "2026-06-05"',
                '  in_sample_end: "2025-12-31"',
                '  out_sample_start: "2026-01-02"',
                "  initial_cash: 1000000.0",
                "  rebalance: monthly",
                "  allow_demo_data: false",
                "data:",
                "  source: csv",
                f"  cache_path: '{path.parent / 'research_recent.db'}'",
                "  adjust: qfq",
                "universe:",
                "  index_code: '000906'",
                "  mode: all_a",
                "  include_st: false",
                "  min_history_days: 120",
                "strategy:",
                "  n_holdings: 30",
                "  max_weight: 0.04",
                "risk:",
                "  max_drawdown_stop: 0.2",
                "broker:",
                "  commission_rate: 0.0003",
                "  min_commission: 5.0",
                "  stamp_tax: 0.001",
                "  slippage_bps: 5.0",
                "  price_limit_pct: 0.10",
                "  lot_size: 100",
                "output:",
                f"  results_dir: '{path.parent / 'results'}'",
            ]
        ),
        encoding="utf-8",
    )
