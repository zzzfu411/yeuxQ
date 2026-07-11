from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

from quantify.data.source_qa import (
    build_data_source_qa,
    build_data_source_qa_answers_from_evidence_worksheet,
    build_data_source_qa_evidence_worksheet,
    build_source_qa_evidence_manifest,
    write_data_source_qa,
    write_data_source_qa_answers,
    write_source_qa_evidence_manifest,
)
from quantify.data.source_qa_readiness import (
    build_source_qa_evidence_readiness,
    write_source_qa_evidence_readiness,
)


def test_source_qa_evidence_readiness_blocks_missing_evidence(tmp_path: Path) -> None:
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

    report = build_source_qa_evidence_readiness(
        checklist_path=data_dir / "data_source_qa.json",
        worksheet_path=data_dir / "data_source_qa_evidence_worksheet.csv",
        answers_path=data_dir / "data_source_qa_answers.json",
        evidence_manifest_path=data_dir / "source_qa_evidence_manifest.json",
        review_artifact_path=tmp_path / "review" / "data_source_qa_review.json",
        require_evidence_manifest=True,
    )
    out = write_source_qa_evidence_readiness(report, tmp_path / "review")
    payload = json.loads((out / "source_qa_evidence_readiness.json").read_text(encoding="utf-8"))
    sections = {section["name"]: section for section in payload["sections"]}

    assert report.status == "BLOCK"
    assert sections["worksheet_preflight"]["status"] == "BLOCK"
    assert sections["answers_preflight"]["status"] == "BLOCK"
    assert sections["manifest_preflight"]["status"] == "BLOCK"
    assert Path(sections["strict_source_qa_review"]["artifact"]) == (
        tmp_path / "review" / "data_source_qa_review.json"
    )
    assert "run_data_source_qa_worksheet_preflight.py" in "\n".join(payload["next_commands"])
    assert (out / "source_qa_evidence_readiness.md").exists()


def test_source_qa_evidence_readiness_passes_complete_source_package(tmp_path: Path) -> None:
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
    worksheet = build_data_source_qa_evidence_worksheet(
        checklist_path=data_dir / "data_source_qa.json",
        output_dir=data_dir,
    )
    _write_worksheet_csv(data_dir / "data_source_qa_evidence_worksheet.csv", _filled_rows(worksheet))
    answers = build_data_source_qa_answers_from_evidence_worksheet(
        checklist_path=data_dir / "data_source_qa.json",
        worksheet_path=data_dir / "data_source_qa_evidence_worksheet.csv",
    )
    write_data_source_qa_answers(answers, data_dir / "data_source_qa_answers.json")
    for item in checklist.checklist:
        if item.review_stage == "source" and item.severity == "BLOCK_IF_NO":
            _write_evidence_file(evidence_dir / f"{item.id}_evidence.txt", item.id)
    manifest = build_source_qa_evidence_manifest(
        checklist_path=data_dir / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, data_dir)

    report = build_source_qa_evidence_readiness(
        checklist_path=data_dir / "data_source_qa.json",
        worksheet_path=data_dir / "data_source_qa_evidence_worksheet.csv",
        answers_path=data_dir / "data_source_qa_answers.json",
        evidence_manifest_path=data_dir / "source_qa_evidence_manifest.json",
        evidence_dir=evidence_dir,
        require_evidence_manifest=True,
    )

    assert report.status == "PASS"
    assert all(section.status == "PASS" for section in report.sections)
    assert "run_data_source_qa_review.py" in "\n".join(report.next_commands)


def test_source_qa_evidence_readiness_cli_writes_report_and_returns_block(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "review"
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
            "examples/run_source_qa_evidence_readiness.py",
            "--checklist",
            str(data_dir / "data_source_qa.json"),
            "--worksheet",
            str(data_dir / "data_source_qa_evidence_worksheet.csv"),
            "--answers",
            str(data_dir / "data_source_qa_answers.json"),
            "--evidence-manifest",
            str(data_dir / "source_qa_evidence_manifest.json"),
            "--require-evidence-manifest",
            "--output-dir",
            str(output),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads((output / "source_qa_evidence_readiness.json").read_text(encoding="utf-8"))

    assert completed.returncode == 2
    assert payload["status"] == "BLOCK"


def _filled_rows(worksheet) -> list[dict[str, str]]:
    values = {
        "data_vendor_or_broker": "unit-test vendor",
        "terminal_or_product_name": "unit-test terminal",
        "export_operator": "tester",
        "exported_at_local_time": "2026-06-08 09:00:00",
        "price_adjustment": "qfq",
        "license_or_usage_scope": "research and paper trading only",
        "reviewed_by": "tester",
        "reviewed_at": "2026-06-08",
    }
    rows: list[dict[str, str]] = []
    for row in worksheet.rows:
        payload = row.to_dict()
        item_id = payload["field_or_question_id"]
        if payload["row_type"] == "metadata":
            payload["answer"] = values.get(item_id, "")
            payload["evidence"] = f"vendor export metadata record for {item_id}"
        elif payload["row_type"] == "source_question":
            payload["answer"] = "yes"
            payload["evidence"] = f"retained source QA evidence for {item_id}"
        rows.append(payload)
    return rows


def _write_worksheet_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "row_type",
        "field_or_question_id",
        "cli_argument",
        "severity",
        "question_or_field",
        "required_evidence",
        "why_it_matters",
        "answer",
        "evidence",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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
            ]
        )
        + "\n",
        encoding="utf-8",
    )
