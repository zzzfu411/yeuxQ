from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

from quantify.data.source_qa import build_data_source_qa, write_data_source_qa
from quantify.data.source_qa_worksheet_fill import fill_source_qa_evidence_worksheet


def test_fill_source_qa_worksheet_passes_preflight_with_explicit_inputs(tmp_path: Path) -> None:
    output = _write_source_qa_artifacts(tmp_path)

    report, preflight = fill_source_qa_evidence_worksheet(
        checklist_path=output / "data_source_qa.json",
        worksheet_path=output / "data_source_qa_evidence_worksheet.csv",
        vendor="verified vendor",
        terminal="verified terminal v1",
        operator="data operator",
        exported_at="2026-06-08 09:00:00",
        price_adjustment="qfq",
        license_scope="research and paper trading only",
        reviewed_by="source reviewer",
        reviewed_at="2026-06-08",
        source_identity_evidence="retained vendor receipt confirms terminal, operator, and export time",
        license_evidence="retained vendor license note permits research and paper review",
        price_adjustment_evidence="retained export setting screenshot confirms qfq adjustment",
        point_in_time_evidence="retained PIT policy note; non-PIT fields stay research-only",
        manual_signoff_evidence="retained reviewer signoff note for the export batch",
    )
    rows = list(csv.DictReader((output / "data_source_qa_evidence_worksheet.csv").open(encoding="utf-8-sig")))
    by_id = {row["field_or_question_id"]: row for row in rows}

    assert report.status == "PASS"
    assert preflight.status == "PASS"
    assert by_id["data_vendor_or_broker"]["answer"] == "verified vendor"
    assert by_id["source_identity"]["answer"] == "yes"
    assert by_id["point_in_time"]["evidence"].startswith("retained PIT policy note")
    assert (output / "data_source_qa_worksheet_fill.json").exists()
    assert not (output / "data_source_qa_answers.json").exists()
    assert not (output / "source_qa_evidence_manifest.json").exists()


def test_fill_source_qa_worksheet_cli_blocks_missing_required_inputs(tmp_path: Path) -> None:
    output = _write_source_qa_artifacts(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/fill_data_source_qa_evidence_worksheet.py",
            "--checklist",
            str(output / "data_source_qa.json"),
            "--worksheet",
            str(output / "data_source_qa_evidence_worksheet.csv"),
            "--vendor",
            "verified vendor",
            "--terminal",
            "verified terminal v1",
            "--operator",
            "data operator",
            "--exported-at",
            "2026-06-08 09:00:00",
            "--price-adjustment",
            "qfq",
            "--license-scope",
            "research and paper trading only",
            "--reviewed-by",
            "source reviewer",
            "--reviewed-at",
            "2026-06-08",
            "--source-identity-evidence",
            "retained vendor receipt confirms terminal, operator, and export time",
            "--license-evidence",
            "retained vendor license note permits research and paper review",
            "--price-adjustment-evidence",
            "retained export setting screenshot confirms qfq adjustment",
            "--point-in-time-evidence",
            "retained PIT policy note; non-PIT fields stay research-only",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads((output / "data_source_qa_worksheet_fill.json").read_text(encoding="utf-8"))

    assert completed.returncode == 2
    assert payload["status"] == "BLOCK"
    assert "--manual-signoff-evidence" in payload["missing_inputs"]
    assert not (output / "data_source_qa_answers.json").exists()


def test_fill_source_qa_worksheet_cli_blocks_generated_evidence_references(tmp_path: Path) -> None:
    output = _write_source_qa_artifacts(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/fill_data_source_qa_evidence_worksheet.py",
            "--checklist",
            str(output / "data_source_qa.json"),
            "--worksheet",
            str(output / "data_source_qa_evidence_worksheet.csv"),
            "--vendor",
            "verified vendor",
            "--terminal",
            "verified terminal v1",
            "--operator",
            "data operator",
            "--exported-at",
            "2026-06-08 09:00:00",
            "--price-adjustment",
            "qfq",
            "--license-scope",
            "research and paper trading only",
            "--reviewed-by",
            "source reviewer",
            "--reviewed-at",
            "2026-06-08",
            "--source-identity-evidence",
            "data_source_qa_evidence_worksheet.csv",
            "--license-evidence",
            "retained vendor license note permits research and paper review",
            "--price-adjustment-evidence",
            "retained export setting screenshot confirms qfq adjustment",
            "--point-in-time-evidence",
            "retained PIT policy note; non-PIT fields stay research-only",
            "--manual-signoff-evidence",
            "retained reviewer signoff note for the export batch",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    fill_payload = json.loads((output / "data_source_qa_worksheet_fill.json").read_text(encoding="utf-8"))
    preflight = json.loads((output / "data_source_qa_worksheet_preflight.json").read_text(encoding="utf-8"))

    assert completed.returncode == 2
    assert fill_payload["status"] == "BLOCK"
    assert preflight["status"] == "BLOCK"
    assert any(
        finding["code"] == "SOURCE_QA_WORKSHEET_GENERATED_EVIDENCE_REFERENCE"
        for finding in preflight["findings"]
    )
    assert not (output / "data_source_qa_answers.json").exists()


def _write_source_qa_artifacts(tmp_path: Path) -> Path:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    return output


def _write_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "research:",
                '  start: "2024-06-03"',
                '  end: "2026-06-05"',
                "data:",
                '  cache_path: "./data_cache/research_recent.db"',
                "  adjust: qfq",
                "universe:",
                "  mode: all_a",
                '  index_code: "000906"',
                "  include_st: false",
                "  min_history_days: 120",
            ]
        ),
        encoding="utf-8",
    )
