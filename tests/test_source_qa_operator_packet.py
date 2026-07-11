from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

from quantify.data.source_qa_operator_packet import (
    build_source_qa_operator_packet,
    write_source_qa_evidence_dropzone_kit,
    write_source_qa_operator_packet,
)


def test_source_qa_operator_packet_consolidates_worksheet_and_attachments(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    _write_operator_inputs(data_dir, report_dir)

    packet = build_source_qa_operator_packet(
        data_dir=data_dir,
        report_dir=report_dir,
        as_of="2026-06-10",
    )
    out = write_source_qa_operator_packet(packet, report_dir)

    payload = json.loads((out / "source_qa_operator_packet.json").read_text(encoding="utf-8"))
    markdown = (out / "source_qa_operator_packet.md").read_text(encoding="utf-8")
    rows = list(csv.DictReader((out / "source_qa_operator_packet.csv").open(encoding="utf-8-sig")))

    assert packet.decision == "BLOCK"
    assert payload["missing_worksheet_count"] == 2
    assert payload["missing_attachment_count"] == 2
    assert payload["dropzone_kit"]["readme_path"].endswith("README_source_qa_evidence_dropzone.md")
    assert payload["dropzone_kit"]["required_files"][0]["id"] == "source_identity"
    assert len(payload["items"]) == 4
    assert payload["items"][0]["item_type"] == "worksheet_metadata"
    assert payload["items"][0]["item_id"] == "data_vendor_or_broker"
    assert "real vendor/export record" in payload["items"][0]["answer_required"]
    assert payload["items"][2]["item_type"] == "attachment"
    assert payload["items"][2]["target"].endswith("source_identity_receipt.png")
    assert "generated receipts" in payload["items"][2]["unacceptable_evidence"]
    assert "fill_data_source_qa_evidence_worksheet.py" in payload["command_sequence"][0]
    assert "<real-vendor-or-broker>" in payload["command_sequence"][0]
    assert "fill_data_source_qa_evidence_worksheet.py" in payload["items"][0]["command_after_completion"]
    assert any("write_data_source_qa_answers.py" in item for item in payload["command_sequence"])
    assert any("--require-evidence-manifest" in item for item in payload["command_sequence"])
    assert any("write_source_qa_evidence_manifest.py" in item and "--strict" in item for item in payload["command_sequence"])
    assert any("run_source_qa_evidence_readiness.py" in item for item in payload["command_sequence"])
    assert any("Do not fabricate" in item for item in payload["prohibited_actions"])
    assert rows[0]["item_id"] == "data_vendor_or_broker"
    assert "human evidence collection aid" in markdown
    assert "Command Sequence" in markdown


def test_source_qa_operator_packet_writes_dropzone_kit_without_creating_evidence(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    _write_operator_inputs(data_dir, report_dir)

    packet = build_source_qa_operator_packet(
        data_dir=data_dir,
        report_dir=report_dir,
        as_of="2026-06-10",
    )
    readme = write_source_qa_evidence_dropzone_kit(packet)
    markdown = readme.read_text(encoding="utf-8")

    assert readme == data_dir / "source_qa_evidence" / "README_source_qa_evidence_dropzone.md"
    assert readme.exists()
    assert "Source QA Evidence Dropzone Kit" in markdown
    assert "source_identity_receipt.png" in markdown
    assert "Do not fabricate" in markdown
    assert not (data_dir / "source_qa_evidence" / "source_identity_receipt.png").exists()


def test_source_qa_operator_packet_passes_when_no_items_remain(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    data_dir.mkdir()
    report_dir.mkdir()
    _write_csv(report_dir / "source_qa_worksheet_todo.csv", ["id"], [])
    _write_csv(report_dir / "source_qa_evidence_attachment_plan.csv", ["id"], [])
    _write_json(report_dir / "first_million_daily_brief.json", {"as_of": "2026-06-10"})

    packet = build_source_qa_operator_packet(data_dir=data_dir, report_dir=report_dir)

    assert packet.decision == "PASS"
    assert packet.missing_worksheet_count == 0
    assert packet.missing_attachment_count == 0
    assert packet.command_sequence[0].startswith(".\\.venv\\Scripts\\python.exe examples\\run_source_qa_evidence_readiness.py")


def test_source_qa_operator_packet_cli_returns_nonzero_on_block(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    _write_operator_inputs(data_dir, report_dir)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_source_qa_operator_packet.py",
            "--data-dir",
            str(data_dir),
            "--report-dir",
            str(report_dir),
            "--as-of",
            "2026-06-10",
            "--write-dropzone-kit",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((report_dir / "source_qa_operator_packet.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"
    assert (data_dir / "source_qa_evidence" / "README_source_qa_evidence_dropzone.md").exists()


def _write_operator_inputs(data_dir: Path, report_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_json(report_dir / "first_million_daily_brief.json", {"as_of": "2026-06-10"})
    _write_csv(
        report_dir / "source_qa_worksheet_todo.csv",
        [
            "row_number",
            "row_type",
            "id",
            "severity",
            "question_or_field",
            "required_evidence",
            "message",
        ],
        [
            {
                "row_number": "2",
                "row_type": "metadata",
                "id": "data_vendor_or_broker",
                "severity": "REQUIRED",
                "question_or_field": "data_vendor_or_broker",
                "required_evidence": "Exact vendor, broker, or terminal data source name.",
                "message": "Required source metadata answer is missing.",
            },
            {
                "row_number": "10",
                "row_type": "source_question",
                "id": "source_identity",
                "severity": "BLOCK_IF_NO",
                "question_or_field": "Can the source be identified?",
                "required_evidence": "Filled source_metadata fields or a vendor export receipt.",
                "message": "BLOCK_IF_NO source QA question is not explicitly answered yes.",
            },
        ],
    )
    _write_csv(
        report_dir / "source_qa_evidence_attachment_plan.csv",
        [
            "id",
            "suggested_file",
            "current_state",
            "required_evidence",
            "do_not_use",
            "next_command",
        ],
        [
            {
                "id": "source_identity",
                "suggested_file": str(data_dir / "source_qa_evidence" / "source_identity_receipt.png"),
                "current_state": "manifest_empty",
                "required_evidence": "Filled source_metadata fields or a vendor export receipt.",
                "do_not_use": "generated receipts",
                "next_command": "write manifest",
            },
            {
                "id": "license_scope",
                "suggested_file": str(data_dir / "source_qa_evidence" / "license_scope_note.pdf"),
                "current_state": "manifest_empty",
                "required_evidence": "License note or account permission.",
                "do_not_use": "assumed license text",
                "next_command": "write manifest",
            },
        ],
    )


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
