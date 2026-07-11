from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

from quantify.data.csv_contract import write_research_csv_templates
from quantify.data.evidence_packet import (
    build_data_evidence_action_packet,
    build_operator_handoff_status,
    write_data_evidence_action_packet,
)
from quantify.data.source_qa import (
    build_data_source_qa,
    build_source_qa_evidence_manifest,
    write_data_source_qa,
    write_source_qa_evidence_manifest,
)
from tests.test_data_gap_action_plan import (
    _write_config,
    _write_placeholder_source_answers,
    _write_replaced_export,
    _write_source_answers,
)


def test_data_evidence_action_packet_blocks_missing_source_qa_and_templates(
    tmp_path: Path,
) -> None:
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

    packet = build_data_evidence_action_packet(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        as_of="2024-01-03",
    )
    out = write_data_evidence_action_packet(packet, tmp_path / "out")

    payload = json.loads((out / "data_evidence_action_packet.json").read_text(encoding="utf-8"))
    todo_rows = list(csv.DictReader((out / "source_qa_worksheet_todo.csv").open(encoding="utf-8-sig")))
    export_rows = list(csv.DictReader((out / "data_export_todo.csv").open(encoding="utf-8-sig")))
    handoff_rows = list(csv.DictReader((out / "operator_handoff.csv").open(encoding="utf-8-sig")))
    attachment_plan_rows = list(
        csv.DictReader((out / "source_qa_evidence_attachment_plan.csv").open(encoding="utf-8-sig"))
    )
    blocker_names = {item["name"] for item in payload["current_blockers"]}
    commands = "\n".join(payload["immediate_commands"])
    markdown = (out / "data_evidence_action_packet.md").read_text(encoding="utf-8")
    handoff_markdown = (out / "operator_handoff.md").read_text(encoding="utf-8")
    attachment_plan_markdown = (out / "source_qa_evidence_attachment_plan.md").read_text(encoding="utf-8")
    evidence_readme = (data_dir / "source_qa_evidence" / "README.md").read_text(encoding="utf-8")
    status_payload = json.loads((out / "operator_handoff_status.json").read_text(encoding="utf-8"))
    status_markdown = (out / "operator_handoff_status.md").read_text(encoding="utf-8")
    evidence_ids = {item["id"] for item in payload["source_qa_evidence_to_fill"]}
    worksheet = payload["source_qa_worksheet_status"]
    assert payload["decision"] == "BLOCK"
    assert "source_qa_answers" in blocker_names
    assert "csv_template_rows" in blocker_names
    assert worksheet["status"] == "BLOCK"
    assert worksheet["missing_row_count"] > 0
    assert any(item["id"] == "data_vendor_or_broker" for item in worksheet["missing_rows"])
    assert "--worksheet" in worksheet["next_command"]
    assert (out / "source_qa_worksheet_todo.md").exists()
    assert (out / "source_qa_attachment_todo.csv").exists()
    assert (out / "source_qa_attachment_todo.md").exists()
    assert (out / "source_qa_evidence_attachment_plan.csv").exists()
    assert (out / "source_qa_evidence_attachment_plan.md").exists()
    assert (data_dir / "source_qa_evidence" / "README.md").exists()
    assert (out / "data_export_todo.md").exists()
    assert (out / "operator_handoff.csv").exists()
    assert (out / "operator_handoff.md").exists()
    assert any(row["id"] == "data_vendor_or_broker" for row in todo_rows)
    assert any(row["required_evidence"] for row in todo_rows)
    first_todo = next(row for row in todo_rows if row["id"] == "data_vendor_or_broker")
    assert first_todo["row_number"] == "2"
    bars_row = next(row for row in export_rows if row["file_name"] == "bars.csv")
    assert bars_row["status"] == "BLOCK"
    assert "Replace generated template" in bars_row["action"]
    assert "TEMPLATE_EXPORT_UNREPLACED" in bars_row["action"]
    assert "minimum symbol count" in bars_row["acceptance_criteria"]
    assert bars_row["exists"] == "yes"
    assert bars_row["row_count"] == "4"
    assert bars_row["symbol_count"] == "2"
    assert bars_row["start"] == "2024-01-02"
    assert bars_row["end"] == "2024-01-03"
    assert bars_row["template_rows_detected"] == "yes"
    assert bars_row["current_state"] == "template_sample_rows"
    assert bars_row["preview_status"] == "PASS"
    assert "symbol" in bars_row["raw_columns"]
    assert "close" in bars_row["mapped_columns"]
    assert bars_row["missing_columns"] == ""
    assert any(item["file_name"] == "bars.csv" for item in payload["required_exports"])
    assert "data_vendor_or_broker" in payload["source_qa_fields_to_fill"]
    assert "data_vendor_or_broker" in payload["source_metadata_fields_to_fill"]
    assert {"license_scope", "price_adjustment", "point_in_time", "manual_signoff"}.issubset(
        evidence_ids
    )
    manifest_status = payload["source_qa_evidence_manifest_status"]
    assert manifest_status["status"] == "BLOCK"
    assert manifest_status["missing_attachment_count"] == 5
    assert {
        "source_identity",
        "license_scope",
        "price_adjustment",
        "point_in_time",
        "manual_signoff",
    }.issubset(set(manifest_status["missing_attachment_ids"]))
    assert payload["immediate_commands"][0].startswith(
        ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa.py"
    )
    assert "write_data_source_qa_evidence_worksheet.py" in commands
    assert "run_source_qa_preflight.py" in commands
    assert "Do not fabricate" in "\n".join(payload["prohibited_actions"])
    assert {row["id"] for row in attachment_plan_rows} == set(manifest_status["missing_attachment_ids"])
    source_identity_plan = next(row for row in attachment_plan_rows if row["id"] == "source_identity")
    assert source_identity_plan["suggested_file"].endswith("source_identity_receipt.png")
    assert "generated receipts" in source_identity_plan["do_not_use"]
    assert "write_source_qa_evidence_manifest.py" in source_identity_plan["next_command"]
    assert "--strict" in source_identity_plan["next_command"]
    assert "Data Evidence Action Packet" in markdown
    assert "Source QA Evidence To Fill" in markdown
    assert "Source QA Worksheet Status" in markdown
    assert "Source QA Evidence Manifest Status" in markdown
    assert "Source QA Evidence Attachment Plan" in attachment_plan_markdown
    assert "Do not use generated placeholder files" in attachment_plan_markdown
    assert "Source QA Evidence Folder" in evidence_readme
    assert "source_qa_evidence_attachment_plan.csv" in evidence_readme
    assert "blank PDFs" in evidence_readme
    handoff_task_types = {row["task_type"] for row in handoff_rows}
    assert {"source_qa_worksheet", "source_qa_attachment", "data_export"}.issubset(
        handoff_task_types
    )
    source_task = next(row for row in handoff_rows if row["id"] == "data_vendor_or_broker")
    assert source_task["row_number"] == "2"
    assert source_task["priority"] == "P0"
    assert source_task["status"] == "BLOCK"
    assert source_task["required_evidence"]
    assert "run_data_source_qa_worksheet_preflight.py" in source_task["next_command"]
    assert "deterministic" in source_task["gate_note"]
    bars_task = next(
        row
        for row in handoff_rows
        if row["task_type"] == "data_export" and row["file_name"] == "bars.csv"
    )
    assert bars_task["status"] == "BLOCK"
    assert "Replace generated template" in bars_task["action"]
    assert "minimum symbol count" in bars_task["acceptance_criteria"]
    assert bars_task["current_state"] == "template_sample_rows"
    assert bars_task["row_count"] == "4"
    assert bars_task["symbol_count"] == "2"
    assert bars_task["template_rows_detected"] == "yes"
    assert bars_task["preview_status"] == "PASS"
    assert "close" in bars_task["mapped_columns"]
    assert "Real Data Operator Handoff" in handoff_markdown
    assert "Source QA Worksheet Tasks" in handoff_markdown
    assert "Source QA Attachment Tasks" in handoff_markdown
    assert "Data Export Tasks" in handoff_markdown
    assert "template_sample_rows" in handoff_markdown
    assert "Completion Criteria" in handoff_markdown
    assert "Do not fabricate" in handoff_markdown
    assert status_payload["status"] == "BLOCK"
    assert status_payload["packet_decision"] == "BLOCK"
    assert status_payload["open_task_count"] == len(handoff_rows)
    assert status_payload["p0_open_task_count"] == len(handoff_rows)
    assert status_payload["source_qa_open_task_count"] == len(todo_rows) + 5
    assert status_payload["source_qa_attachment_open_task_count"] == 5
    assert status_payload["data_export_open_task_count"] == len(export_rows)
    assert status_payload["next_batch"]["status"] == "BLOCK"
    assert status_payload["next_batch"]["task_type"] == "source_qa_worksheet"
    assert status_payload["next_batch"]["task_count"] == len(todo_rows)
    assert status_payload["next_batch"]["sample_tasks"][0]["item"] == "row 2: data_vendor_or_broker"
    assert "data_source_qa_answers.json" in status_payload["next_batch"]["acceptance_criteria"]
    assert status_payload["first_open_tasks"][0]["item"] == "row 2: data_vendor_or_broker"
    assert status_payload["first_open_tasks"][0]["target"].endswith(
        "data_source_qa_evidence_worksheet.csv"
    )
    assert "run_data_source_qa_worksheet_preflight.py" in status_payload["first_open_tasks"][0]["next_command"]
    assert "required_evidence" in status_payload["first_open_tasks"][0]
    assert "Operator Handoff Status" in status_markdown
    assert "Next Batch" in status_markdown
    assert "not a strategy approval" in status_markdown
    assert "next command" in status_markdown


def test_data_evidence_action_packet_reports_filled_worksheet_before_answers(
    tmp_path: Path,
) -> None:
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
    _fill_worksheet(data_dir / "data_source_qa_evidence_worksheet.csv")

    packet = build_data_evidence_action_packet(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        as_of="2024-01-03",
    )
    out = write_data_evidence_action_packet(packet, tmp_path / "out")

    worksheet = packet.to_dict()["source_qa_worksheet_status"]
    manifest_status = packet.to_dict()["source_qa_evidence_manifest_status"]
    todo_rows = list(csv.DictReader((out / "source_qa_worksheet_todo.csv").open(encoding="utf-8-sig")))
    attachment_rows = list(csv.DictReader((out / "source_qa_attachment_todo.csv").open(encoding="utf-8-sig")))
    handoff_rows = list(csv.DictReader((out / "operator_handoff.csv").open(encoding="utf-8-sig")))
    handoff_md = (out / "operator_handoff.md").read_text(encoding="utf-8")
    status_payload = json.loads((out / "operator_handoff_status.json").read_text(encoding="utf-8"))
    assert packet.decision == "BLOCK"
    assert worksheet["status"] == "PASS"
    assert worksheet["missing_row_count"] == 0
    assert manifest_status["status"] == "BLOCK"
    assert manifest_status["missing_attachment_count"] == 5
    assert todo_rows == []
    assert len(attachment_rows) == 5
    assert "run_data_source_qa_worksheet_preflight.py" in worksheet["next_command"]
    assert "write_data_source_qa_answers.py" in worksheet["answers_command"]
    assert "--worksheet" in worksheet["next_command"]
    assert not any(row["task_type"] == "source_qa_worksheet" for row in handoff_rows)
    assert any(row["task_type"] == "source_qa_attachment" for row in handoff_rows)
    assert any(row["task_type"] == "data_export" for row in handoff_rows)
    assert "write_data_source_qa_answers.py" in handoff_md
    assert "source_qa_evidence_manifest.json" in handoff_md
    assert status_payload["status"] == "BLOCK"
    assert status_payload["source_qa_open_task_count"] == len(attachment_rows)
    assert status_payload["source_qa_attachment_open_task_count"] == len(attachment_rows)
    assert status_payload["data_export_open_task_count"] == len(handoff_rows) - len(attachment_rows)
    assert status_payload["next_batch"]["task_type"] == "source_qa_attachment"
    assert status_payload["next_batch"]["task_count"] == len(attachment_rows)
    assert "--strict" in status_payload["next_batch"]["next_command"]
    assert "source_qa_evidence_manifest.json" in status_payload["next_batch"]["acceptance_criteria"]


def test_data_evidence_action_packet_blocks_generated_worksheet_evidence_path(
    tmp_path: Path,
) -> None:
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
    _fill_worksheet(data_dir / "data_source_qa_evidence_worksheet.csv")
    _replace_worksheet_evidence(
        data_dir / "data_source_qa_evidence_worksheet.csv",
        item_id="license_scope",
        evidence="source_qa_evidence_attachment_plan.csv",
    )

    packet = build_data_evidence_action_packet(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        as_of="2024-01-03",
    )
    out = write_data_evidence_action_packet(packet, tmp_path / "out")
    handoff_rows = list(csv.DictReader((out / "operator_handoff.csv").open(encoding="utf-8-sig")))
    license_task = next(row for row in handoff_rows if row["id"] == "license_scope")

    assert packet.source_qa_worksheet_status["status"] == "BLOCK"
    assert license_task["priority"] == "P0"
    assert license_task["status"] == "BLOCK"
    assert license_task["current_state"] == "source_qa_worksheet_generated_evidence_reference"


def test_data_evidence_action_packet_passes_to_final_import_commands(tmp_path: Path) -> None:
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
    _write_required_source_qa_attachments(data_dir, checklist.to_dict())

    packet = build_data_evidence_action_packet(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        as_of="2024-01-03",
    )

    commands = "\n".join(packet.immediate_commands)
    worksheet = packet.to_dict()["source_qa_worksheet_status"]
    manifest_status = packet.to_dict()["source_qa_evidence_manifest_status"]
    out = write_data_evidence_action_packet(packet, tmp_path / "out")
    export_rows = list(csv.DictReader((out / "data_export_todo.csv").open(encoding="utf-8-sig")))
    attachment_rows = list(csv.DictReader((out / "source_qa_attachment_todo.csv").open(encoding="utf-8-sig")))
    attachment_plan_rows = list(
        csv.DictReader((out / "source_qa_evidence_attachment_plan.csv").open(encoding="utf-8-sig"))
    )
    handoff_rows = list(csv.DictReader((out / "operator_handoff.csv").open(encoding="utf-8-sig")))
    attachment_plan_md = (out / "source_qa_evidence_attachment_plan.md").read_text(encoding="utf-8")
    evidence_readme = (data_dir / "source_qa_evidence" / "README.md").read_text(encoding="utf-8")
    handoff_md = (out / "operator_handoff.md").read_text(encoding="utf-8")
    status_payload = json.loads((out / "operator_handoff_status.json").read_text(encoding="utf-8"))
    assert packet.decision == "PASS"
    assert worksheet["status"] == "ANSWERS_PRESENT"
    assert manifest_status["status"] == "PASS"
    assert manifest_status["missing_attachment_count"] == 0
    assert attachment_rows == []
    assert attachment_plan_rows == []
    bars_row = next(row for row in export_rows if row["file_name"] == "bars.csv")
    assert bars_row["exists"] == "yes"
    assert bars_row["row_count"] == "4"
    assert bars_row["symbol_count"] == "2"
    assert bars_row["start"] == "2024-01-02"
    assert bars_row["end"] == "2024-01-03"
    assert bars_row["template_rows_detected"] == "no"
    assert bars_row["current_state"] == "present_needs_validation"
    assert bars_row["preview_status"] == "PASS"
    assert "symbol" in bars_row["mapped_columns"]
    assert packet.current_blockers == []
    assert len(packet.immediate_commands) == 2
    assert "run_offline_data_intake.py" in commands
    assert "run_first_million_pipeline.py" in commands
    assert handoff_rows
    assert not any(row["task_type"] == "source_qa_worksheet" for row in handoff_rows)
    assert not any(row["task_type"] == "source_qa_attachment" for row in handoff_rows)
    bars_task = next(row for row in handoff_rows if row["file_name"] == "bars.csv")
    assert bars_task["current_state"] == "present_needs_validation"
    assert bars_task["row_count"] == "4"
    assert bars_task["symbol_count"] == "2"
    assert bars_task["template_rows_detected"] == "no"
    assert bars_task["preview_status"] == "PASS"
    assert all("approval" in row["gate_note"] for row in handoff_rows)
    assert "run_offline_data_intake.py" in handoff_md
    assert "run_first_million_pipeline.py" in handoff_md
    assert "does not approve" in handoff_md
    assert "Required missing/invalid attachments: 0" in attachment_plan_md
    assert "Place only real local evidence files" in evidence_readme
    assert status_payload["status"] == "WATCH"
    assert status_payload["packet_decision"] == "PASS"
    assert status_payload["p0_open_task_count"] == 0
    assert status_payload["p1_open_task_count"] == len(handoff_rows)
    assert status_payload["next_batch"]["task_type"] == "data_export"
    assert status_payload["next_batch"]["priority"] == "P1"
    assert status_payload["next_batch"]["status"] == "WATCH"
    assert "deterministic" in "\n".join(status_payload["next_actions"])


def test_data_evidence_action_packet_keeps_source_tasks_for_placeholder_answers(
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
    _write_placeholder_source_answers(data_dir / "data_source_qa_answers.json", checklist.to_dict())

    packet = build_data_evidence_action_packet(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        as_of="2024-01-03",
    )
    out = write_data_evidence_action_packet(packet, tmp_path / "out")

    payload = json.loads((out / "data_evidence_action_packet.json").read_text(encoding="utf-8"))
    todo_rows = list(csv.DictReader((out / "source_qa_worksheet_todo.csv").open(encoding="utf-8-sig")))
    attachment_rows = list(csv.DictReader((out / "source_qa_attachment_todo.csv").open(encoding="utf-8-sig")))
    handoff_rows = list(csv.DictReader((out / "operator_handoff.csv").open(encoding="utf-8-sig")))
    status_payload = json.loads((out / "operator_handoff_status.json").read_text(encoding="utf-8"))
    worksheet = payload["source_qa_worksheet_status"]

    assert packet.decision == "BLOCK"
    assert worksheet["status"] == "BLOCK"
    assert worksheet["missing_row_count"] > 0
    assert any(row["id"] == "data_vendor_or_broker" for row in todo_rows)
    assert any(row["id"] == "price_adjustment" for row in todo_rows)
    assert any("data_source_qa_answers.json" in row["message"] for row in todo_rows)
    assert any(row["task_type"] == "source_qa_worksheet" for row in handoff_rows)
    assert any(row["task_type"] == "source_qa_attachment" for row in handoff_rows)
    assert status_payload["source_qa_open_task_count"] == len(todo_rows) + len(attachment_rows)
    assert status_payload["source_qa_attachment_open_task_count"] == len(attachment_rows)
    assert status_payload["p0_open_task_count"] >= 1


def test_data_evidence_action_packet_surfaces_invalid_attachment_manifest(
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
    _write_source_answers(data_dir / "data_source_qa_answers.json", checklist.to_dict())
    _write_required_source_qa_attachments(data_dir, checklist.to_dict())
    changed = data_dir / "source_qa_evidence" / "source_identity_evidence.txt"
    changed.write_text("changed after manifest", encoding="utf-8")

    packet = build_data_evidence_action_packet(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        as_of="2024-01-03",
    )
    out = write_data_evidence_action_packet(packet, tmp_path / "out")

    payload = json.loads((out / "data_evidence_action_packet.json").read_text(encoding="utf-8"))
    attachment_rows = list(csv.DictReader((out / "source_qa_attachment_todo.csv").open(encoding="utf-8-sig")))
    handoff_rows = list(csv.DictReader((out / "operator_handoff.csv").open(encoding="utf-8-sig")))
    status_payload = json.loads((out / "operator_handoff_status.json").read_text(encoding="utf-8"))
    manifest_status = payload["source_qa_evidence_manifest_status"]

    assert manifest_status["status"] == "BLOCK"
    assert manifest_status["missing_attachment_count"] == 1
    assert manifest_status["invalid_attachment_count"] == 1
    assert "source_identity" in manifest_status["invalid_attachment_ids"]
    invalid_target = next(
        item
        for item in manifest_status["invalid_attachment_targets"]
        if item["id"] == "source_identity"
    )
    assert invalid_target["path"] == str(changed)
    assert invalid_target["current_state"] == "sha256_mismatch"
    assert invalid_target["message"]
    assert attachment_rows
    assert any(row["id"] == "source_identity" for row in attachment_rows)
    assert any(row["current_state"] == "sha256_mismatch" for row in attachment_rows)
    assert any(row["task_type"] == "source_qa_attachment" for row in handoff_rows)
    assert status_payload["status"] == "BLOCK"
    assert status_payload["source_qa_attachment_open_task_count"] >= 1
    first_task = status_payload["first_open_tasks"][0]
    assert first_task["item"] == "attachment: source_identity"
    assert first_task["target"]
    assert first_task["next_command"]
    assert "--strict" in first_task["next_command"]
    assert first_task["current_state"] == "sha256_mismatch"


def test_data_evidence_action_packet_keeps_placeholder_attachment_tasks_open(
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
    _write_source_answers(data_dir / "data_source_qa_answers.json", checklist.to_dict())
    evidence_dir = data_dir / "source_qa_evidence"
    for item in checklist.checklist:
        if item.review_stage == "source" and item.severity == "BLOCK_IF_NO":
            path = evidence_dir / f"{item.id}_evidence.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"generated placeholder evidence for {item.id}", encoding="utf-8")
    manifest = build_source_qa_evidence_manifest(
        checklist_path=data_dir / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, data_dir)

    packet = build_data_evidence_action_packet(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        as_of="2024-01-03",
    )
    out = write_data_evidence_action_packet(packet, tmp_path / "out")

    payload = json.loads((out / "data_evidence_action_packet.json").read_text(encoding="utf-8"))
    attachment_rows = list(csv.DictReader((out / "source_qa_attachment_todo.csv").open(encoding="utf-8-sig")))
    handoff_rows = list(csv.DictReader((out / "operator_handoff.csv").open(encoding="utf-8-sig")))
    status_payload = json.loads((out / "operator_handoff_status.json").read_text(encoding="utf-8"))
    manifest_status = payload["source_qa_evidence_manifest_status"]

    assert packet.decision == "BLOCK"
    assert manifest_status["status"] == "BLOCK"
    assert manifest_status["invalid_attachment_count"] >= 1
    assert "source_identity" in manifest_status["invalid_attachment_ids"]
    assert any(item["current_state"] == "placeholder_content" for item in manifest_status["invalid_attachment_targets"])
    assert any(row["current_state"] == "placeholder_content" for row in attachment_rows)
    assert any(row["task_type"] == "source_qa_attachment" for row in handoff_rows)
    assert status_payload["status"] == "BLOCK"
    assert status_payload["source_qa_attachment_open_task_count"] >= 1
    assert status_payload["first_open_tasks"][0]["current_state"] == "placeholder_content"


def test_data_evidence_action_packet_keeps_generated_path_attachment_tasks_open(
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
    _write_source_answers(data_dir / "data_source_qa_answers.json", checklist.to_dict())
    evidence_dir = data_dir / "source_qa_evidence"
    for item in checklist.checklist:
        if item.review_stage != "source" or item.severity != "BLOCK_IF_NO":
            continue
        file_name = "source_identity_worksheet.txt" if item.id == "source_identity" else f"{item.id}_evidence.txt"
        path = evidence_dir / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"vendor export audit note for {item.id}: retained screenshot/document reviewed by tester.",
            encoding="utf-8",
        )
    manifest = build_source_qa_evidence_manifest(
        checklist_path=data_dir / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, data_dir)

    packet = build_data_evidence_action_packet(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        as_of="2024-01-03",
    )
    out = write_data_evidence_action_packet(packet, tmp_path / "out")

    payload = json.loads((out / "data_evidence_action_packet.json").read_text(encoding="utf-8"))
    attachment_rows = list(csv.DictReader((out / "source_qa_attachment_todo.csv").open(encoding="utf-8-sig")))
    handoff_rows = list(csv.DictReader((out / "operator_handoff.csv").open(encoding="utf-8-sig")))
    status_payload = json.loads((out / "operator_handoff_status.json").read_text(encoding="utf-8"))
    manifest_status = payload["source_qa_evidence_manifest_status"]

    assert packet.decision == "BLOCK"
    assert manifest_status["status"] == "BLOCK"
    assert "source_identity" in manifest_status["invalid_attachment_ids"]
    assert any(
        item["current_state"] == "generated_artifact_path"
        for item in manifest_status["invalid_attachment_targets"]
    )
    assert any(row["current_state"] == "generated_artifact_path" for row in attachment_rows)
    assert any(row["task_type"] == "source_qa_attachment" for row in handoff_rows)
    assert status_payload["status"] == "BLOCK"
    assert status_payload["source_qa_attachment_open_task_count"] >= 1
    assert status_payload["first_open_tasks"][0]["current_state"] == "generated_artifact_path"


def test_operator_handoff_status_can_be_built_from_existing_csv(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)

    packet = build_data_evidence_action_packet(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        as_of="2024-01-03",
    )
    out = write_data_evidence_action_packet(packet, tmp_path / "out")
    status = build_operator_handoff_status(
        packet=packet,
        operator_handoff_path=out / "operator_handoff.csv",
    )

    assert status.status == "BLOCK"
    assert status.p0_open_task_count > 0
    assert status.first_open_tasks
    assert status.first_open_tasks[0]["item"] == "data_source_qa_evidence_worksheet"
    assert status.first_open_tasks[0]["target"].endswith("data_source_qa_evidence_worksheet.csv")
    assert "write_data_source_qa_evidence_worksheet.py" in status.first_open_tasks[0]["next_command"]
    assert status.next_batch["task_type"] == "source_qa_worksheet"
    assert status.next_batch["sample_tasks"][0]["item"] == "data_source_qa_evidence_worksheet"
    assert any(
        task["item"] == "data_source_qa_evidence_worksheet"
        for task in status.first_open_tasks
    )


def test_data_evidence_action_packet_cli_writes_block_report(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    output = tmp_path / "out"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/write_data_evidence_action_packet.py",
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

    payload = json.loads((output / "data_evidence_action_packet.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"
    assert (output / "data_evidence_action_packet.md").exists()
    assert (output / "operator_handoff.csv").exists()
    assert (output / "operator_handoff.md").exists()
    assert (output / "operator_handoff_status.json").exists()
    assert (output / "operator_handoff_status.md").exists()


def test_operator_handoff_status_cli_writes_block_report(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    output = tmp_path / "out"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_operator_handoff_status.py",
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

    payload = json.loads((output / "operator_handoff_status.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["status"] == "BLOCK"
    assert payload["p0_open_task_count"] > 0


def test_data_evidence_action_packet_surfaces_csv_preview_missing_columns(
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
                "000001,2024-01-02,10,11,9,1000,10000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _write_config(config, cache)

    packet = build_data_evidence_action_packet(
        data_dir=data_dir,
        config_path=config,
        min_symbols=2,
        as_of="2024-01-03",
    )
    out = write_data_evidence_action_packet(packet, tmp_path / "out")

    export_rows = list(csv.DictReader((out / "data_export_todo.csv").open(encoding="utf-8-sig")))
    handoff_rows = list(csv.DictReader((out / "operator_handoff.csv").open(encoding="utf-8-sig")))
    bars_row = next(row for row in export_rows if row["file_name"] == "bars.csv")
    bars_task = next(
        row
        for row in handoff_rows
        if row["task_type"] == "data_export" and row["file_name"] == "bars.csv"
    )

    assert bars_row["preview_status"] == "BLOCK"
    assert "close" in bars_row["missing_columns"]
    assert "Required columns" in bars_row["preview_message"]
    assert bars_task["preview_status"] == "BLOCK"
    assert bars_task["missing_columns"] == bars_row["missing_columns"]


def _fill_worksheet(path: Path) -> None:
    rows: list[dict[str, str]] = []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            payload = {key: str(row.get(key, "") or "") for key in fieldnames}
            item_id = payload["field_or_question_id"]
            if payload["row_type"] == "metadata":
                payload["answer"] = _worksheet_metadata_value(item_id)
                payload["evidence"] = f"real metadata evidence for {item_id}"
            elif payload["row_type"] == "source_question":
                payload["answer"] = "yes"
                payload["evidence"] = f"real source QA evidence for {item_id}"
            rows.append(payload)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _replace_worksheet_evidence(path: Path, *, item_id: str, evidence: str) -> None:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    for row in rows:
        if str(row.get("field_or_question_id", "")) == item_id:
            row["evidence"] = evidence
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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


def _worksheet_metadata_value(item_id: str) -> str:
    return {
        "data_vendor_or_broker": "unit-test vendor",
        "terminal_or_product_name": "unit-test terminal",
        "export_operator": "tester",
        "exported_at_local_time": "2026-06-08 09:00:00",
        "price_adjustment": "qfq",
        "license_or_usage_scope": "research and paper trading only",
        "reviewed_by": "tester",
        "reviewed_at": "2026-06-08",
    }.get(item_id, "unit-test evidence")
