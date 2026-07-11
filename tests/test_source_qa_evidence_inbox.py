from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from quantify.data.source_qa_evidence_inbox import (
    build_source_qa_evidence_inbox,
    write_source_qa_evidence_inbox,
)


def test_source_qa_evidence_inbox_maps_local_files_without_creating_evidence(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    evidence_dir = data_dir / "source_qa_evidence"
    _write_checklist(data_dir)
    _write_attachment_plan(data_dir, report_dir)
    evidence_dir.mkdir(parents=True)
    receipt = evidence_dir / "source_identity_receipt.png"
    receipt.write_bytes(b"\x89PNG\r\nretained vendor export receipt bytes")

    report = build_source_qa_evidence_inbox(
        data_dir=data_dir,
        report_dir=report_dir,
        as_of="2026-06-10",
    )
    out = write_source_qa_evidence_inbox(report, report_dir)

    payload = json.loads((out / "source_qa_evidence_inbox.json").read_text(encoding="utf-8"))
    markdown = (out / "source_qa_evidence_inbox.md").read_text(encoding="utf-8")
    rows = list(csv.DictReader((out / "source_qa_evidence_inbox.csv").open(encoding="utf-8-sig")))

    assert report.status == "BLOCK"
    assert payload["matched_item_count"] == 1
    assert payload["missing_item_count"] == 1
    assert payload["items"][0]["item_id"] == "source_identity"
    assert payload["items"][0]["matched_files"][0]["path"] == str(receipt)
    assert payload["items"][1]["item_id"] == "license_scope"
    assert payload["items"][1]["status"] == "BLOCK"
    assert "--source-identity-evidence" in payload["worksheet_fill_command"]
    assert str(receipt) in payload["worksheet_fill_command"]
    assert "--license-evidence" in payload["worksheet_fill_command"]
    assert payload["worksheet_fill_command_ready"] is False
    assert payload["worksheet_fill_command_status"] == "BLOCK"
    assert "license_scope" in payload["worksheet_fill_command_blockers"][0]
    assert payload["worksheet_fill_args"][0]["source"] == "matched_file"
    assert payload["worksheet_fill_args"][0]["status"] == "PASS"
    assert payload["worksheet_fill_args"][0]["ready"] is True
    assert payload["worksheet_fill_args"][1]["source"] == "target_path"
    assert payload["worksheet_fill_args"][1]["exists"] is False
    assert payload["worksheet_fill_args"][1]["ready"] is False
    assert "does not create evidence" in markdown
    assert "Worksheet Fill Command" in markdown
    assert "target paths and placeholders are not ready evidence" in markdown
    assert rows[0]["item_id"] == "source_identity"
    assert not (evidence_dir / "license_scope_note.pdf").exists()


def test_source_qa_evidence_inbox_marks_only_real_matched_source_args_ready(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    evidence_dir = data_dir / "source_qa_evidence"
    _write_checklist(data_dir)
    _write_attachment_plan(data_dir, report_dir)
    evidence_dir.mkdir(parents=True)
    receipt = evidence_dir / "source_identity_receipt.png"
    receipt.write_bytes(b"\x89PNG\r\nretained vendor export receipt bytes")
    license_note = evidence_dir / "license_scope_account_terms.md"
    license_note.write_text(
        "Retained account permission evidence for the real export batch.",
        encoding="utf-8",
    )

    report = build_source_qa_evidence_inbox(
        data_dir=data_dir,
        report_dir=report_dir,
        as_of="2026-06-10",
    )
    out = write_source_qa_evidence_inbox(report, report_dir)

    payload = json.loads((out / "source_qa_evidence_inbox.json").read_text(encoding="utf-8"))
    markdown = (out / "source_qa_evidence_inbox.md").read_text(encoding="utf-8")
    source_args = {
        item["item_id"]: item
        for item in payload["worksheet_fill_args"]
        if item["cli_argument"].endswith("-evidence")
    }

    assert payload["status"] == "PASS"
    assert payload["matched_item_count"] == 2
    assert payload["missing_item_count"] == 0
    assert payload["worksheet_fill_command_ready"] is True
    assert payload["worksheet_fill_command_status"] == "PASS"
    assert payload["worksheet_fill_command_blockers"] == []
    assert {arg["source"] for arg in source_args.values()} == {"matched_file"}
    assert all(arg["exists"] is True for arg in source_args.values())
    assert all(arg["ready"] is True for arg in source_args.values())
    assert all(arg["status"] == "PASS" for arg in source_args.values())
    assert str(receipt) in payload["worksheet_fill_command"]
    assert str(license_note) in payload["worksheet_fill_command"]
    assert "only ready" in markdown


def test_source_qa_evidence_inbox_keeps_existing_target_path_args_not_ready(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    plan_dir = tmp_path / "operator_plan_targets"
    _write_checklist(data_dir)
    _write_attachment_plan(data_dir, report_dir, target_root=plan_dir)
    target = plan_dir / "source_identity_receipt.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\x89PNG\r\nreal bytes, but not a scanned or manifest-matched inbox file")

    report = build_source_qa_evidence_inbox(
        data_dir=data_dir,
        report_dir=report_dir,
        as_of="2026-06-10",
    )
    out = write_source_qa_evidence_inbox(report, report_dir)

    payload = json.loads((out / "source_qa_evidence_inbox.json").read_text(encoding="utf-8"))
    markdown = (out / "source_qa_evidence_inbox.md").read_text(encoding="utf-8")
    source_identity_arg = next(
        item for item in payload["worksheet_fill_args"] if item["item_id"] == "source_identity"
    )

    assert source_identity_arg["source"] == "target_path"
    assert source_identity_arg["exists"] is True
    assert source_identity_arg["ready"] is False
    assert source_identity_arg["status"] == "BLOCK"
    assert payload["worksheet_fill_command_ready"] is False
    assert "human placeholder" in source_identity_arg["message"]
    assert "human placeholder" in markdown


def test_source_qa_evidence_inbox_surfaces_placeholder_manifest_attachment(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    evidence_dir = data_dir / "source_qa_evidence"
    _write_checklist(data_dir)
    _write_attachment_plan(data_dir, report_dir)
    evidence_dir.mkdir(parents=True)
    source_identity = evidence_dir / "source_identity_receipt.png"
    source_identity.write_bytes(b"\x89PNG\r\nretained vendor export receipt bytes")
    license_note = evidence_dir / "license_scope_note.md"
    license_note.write_text("sample evidence for license scope", encoding="utf-8")
    _write_json(
        data_dir / "source_qa_evidence_manifest.json",
        {
            "items": [
                {
                    "id": "source_identity",
                    "path": str(source_identity),
                    "sha256": _sha(source_identity),
                },
                {
                    "id": "license_scope",
                    "path": str(license_note),
                    "sha256": _sha(license_note),
                },
            ]
        },
    )

    report = build_source_qa_evidence_inbox(data_dir=data_dir, report_dir=report_dir)

    payload = report.to_dict()
    license_item = next(item for item in payload["items"] if item["item_id"] == "license_scope")
    assert report.status == "WATCH"
    assert payload["worksheet_fill_command_ready"] is False
    assert payload["worksheet_fill_command_status"] == "BLOCK"
    assert license_item["status"] == "WATCH"
    assert license_item["matched_files"][0]["validation_error"]["code"] == "placeholder_content"
    assert "license_scope_note.md" in payload["worksheet_fill_command"]
    assert any("invalid" in item for item in payload["next_actions"])


def test_source_qa_evidence_inbox_does_not_use_readme_as_fill_evidence(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    evidence_dir = data_dir / "source_qa_evidence"
    _write_checklist(data_dir)
    _write_attachment_plan(data_dir, report_dir)
    evidence_dir.mkdir(parents=True)
    readme = evidence_dir / "README_source_qa_evidence_dropzone.md"
    readme.write_text("operator instructions only", encoding="utf-8")

    report = build_source_qa_evidence_inbox(
        data_dir=data_dir,
        report_dir=report_dir,
        as_of="2026-06-10",
    )
    payload = report.to_dict()
    source_identity_arg = next(
        item for item in payload["worksheet_fill_args"] if item["item_id"] == "source_identity"
    )

    assert str(readme) not in payload["worksheet_fill_command"]
    assert payload["worksheet_fill_command_ready"] is False
    assert source_identity_arg["source"] == "target_path"
    assert source_identity_arg["exists"] is False
    assert source_identity_arg["ready"] is False
    assert source_identity_arg["status"] == "BLOCK"
    assert "human placeholder" in source_identity_arg["message"]
    assert payload["unmatched_files"][0]["validation_error"]["code"] == "instruction_or_generated_file"


def test_source_qa_evidence_inbox_cli_returns_nonzero_on_missing_items(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    _write_checklist(data_dir)
    _write_attachment_plan(data_dir, report_dir)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_source_qa_evidence_inbox.py",
            "--data-dir",
            str(data_dir),
            "--report-dir",
            str(report_dir),
            "--as-of",
            "2026-06-10",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((report_dir / "source_qa_evidence_inbox.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["status"] == "BLOCK"


def _write_checklist(data_dir: Path) -> None:
    _write_json(
        data_dir / "data_source_qa.json",
        {
            "checklist": [
                {
                    "id": "source_identity",
                    "review_stage": "source",
                    "severity": "BLOCK_IF_NO",
                    "required_evidence": "Vendor export receipt.",
                },
                {
                    "id": "license_scope",
                    "review_stage": "source",
                    "severity": "BLOCK_IF_NO",
                    "required_evidence": "License or account permission.",
                },
            ]
        },
    )


def _write_attachment_plan(data_dir: Path, report_dir: Path, *, target_root: Path | None = None) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    evidence_root = target_root or data_dir / "source_qa_evidence"
    with (report_dir / "source_qa_evidence_attachment_plan.csv").open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "suggested_file",
                "current_state",
                "required_evidence",
                "do_not_use",
                "next_command",
            ],
        )
        writer.writeheader()
        writer.writerows(
            [
                {
                    "id": "source_identity",
                    "suggested_file": str(evidence_root / "source_identity_receipt.png"),
                    "current_state": "missing",
                    "required_evidence": "Vendor export receipt.",
                    "do_not_use": "generated receipt",
                    "next_command": "write manifest",
                },
                {
                    "id": "license_scope",
                    "suggested_file": str(evidence_root / "license_scope_note.pdf"),
                    "current_state": "missing",
                    "required_evidence": "License or account permission.",
                    "do_not_use": "assumed license text",
                    "next_command": "write manifest",
                },
            ]
        )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
