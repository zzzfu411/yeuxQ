from __future__ import annotations

import csv
import json
from pathlib import Path

from quantify.data.source_qa_closeout import build_source_qa_closeout, write_source_qa_closeout
from quantify.data.source_qa_evidence_inbox import (
    SourceQAEvidenceInboxItem,
    SourceQAEvidenceInboxReport,
    SourceQAWorksheetFillArgument,
)
from quantify.data.source_qa_operator_packet import (
    FILL_WORKSHEET_COMMAND,
    PROHIBITED_ACTIONS as OPERATOR_PROHIBITED_ACTIONS,
    STRICT_MANIFEST_COMMAND,
    SourceQAEvidenceDropzoneKit,
    SourceQAOperatorItem,
    SourceQAOperatorPacket,
)
from quantify.data.source_qa_readiness import (
    SourceQAEvidenceReadiness,
    SourceQAEvidenceReadinessSection,
)


def test_source_qa_closeout_blocks_and_prioritizes_real_evidence_collection(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    data_dir.mkdir()
    report_dir.mkdir()

    closeout = build_source_qa_closeout(
        data_dir=data_dir,
        report_dir=report_dir,
        as_of="2026-06-10",
        operator_packet=_blocked_operator_packet(data_dir, report_dir),
        evidence_inbox=_blocked_inbox(data_dir, report_dir),
        evidence_readiness=_blocked_readiness(data_dir, report_dir),
    )
    out = write_source_qa_closeout(closeout, report_dir)

    payload = json.loads((out / "source_qa_closeout.json").read_text(encoding="utf-8"))
    markdown = (out / "source_qa_closeout.md").read_text(encoding="utf-8")
    rows = list(csv.DictReader((out / "source_qa_closeout.csv").open(encoding="utf-8-sig")))

    assert payload["decision"] == "BLOCK"
    assert payload["allowed_next_stage"] == "COLLECT_EVIDENCE"
    assert payload["counts"]["missing_worksheet_count"] == 1
    assert payload["counts"]["missing_attachment_count"] == 1
    assert payload["actions"][0]["category"] == "source_qa_worksheet"
    assert payload["actions"][0]["item"] == "data_vendor_or_broker"
    assert "Start with `source_qa_worksheet/data_vendor_or_broker`" in payload["next_action"]
    assert [step["title"] for step in payload["next_steps"]] == [
        "attach_retained_source_qa_evidence",
        "fill_source_qa_worksheet",
        "rerun_strict_source_qa_review",
    ]
    assert payload["next_steps"][0]["blocks_stage"] == "source_qa_answers"
    assert "source_identity" in payload["next_steps"][0]["required_items"][0]
    assert "data_vendor_or_broker" in payload["next_steps"][1]["required_items"][0]
    assert "write_data_source_qa_answers.py" in payload["next_steps"][2]["command"]
    assert payload["capability_flags"]["can_enter_paper"] is False
    assert payload["capability_flags"]["can_generate_broker_orders"] is False
    assert any(item["name"] == "strict_source_qa_review" for item in payload["artifact_manifest"])
    assert any("run_source_qa_closeout.py" in item for item in payload["command_sequence"])
    assert rows[0]["category"] == "source_qa_worksheet"
    assert "does not create evidence" in markdown


def test_source_qa_closeout_pass_remains_guarded_offline_intake_only(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    _touch_required_artifacts(data_dir, report_dir)

    closeout = build_source_qa_closeout(
        data_dir=data_dir,
        report_dir=report_dir,
        as_of="2026-06-10",
        operator_packet=_pass_operator_packet(data_dir, report_dir),
        evidence_inbox=_pass_inbox(data_dir, report_dir),
        evidence_readiness=_pass_readiness(data_dir, report_dir),
    )

    payload = closeout.to_dict()

    assert payload["decision"] == "PASS"
    assert payload["allowed_next_stage"] == "GUARDED_OFFLINE_INTAKE"
    assert payload["actions"] == []
    assert payload["next_steps"][0]["title"] == "continue_to_guarded_offline_intake"
    assert payload["next_steps"][0]["status"] == "PASS"
    assert "run_first_million_pipeline.py" in payload["next_steps"][0]["command"]
    assert payload["capability_flags"]["source_qa_evidence_complete"] is True
    assert payload["capability_flags"]["can_enter_paper"] is False
    assert payload["capability_flags"]["can_enter_live"] is False
    assert payload["capability_flags"]["can_override_deterministic_gates"] is False
    assert "live" not in payload["allowed_next_stage"].lower()
    assert all(item["exists"] for item in payload["artifact_manifest"])
    assert any("run_first_million_pipeline.py" in item for item in payload["command_sequence"])


def _blocked_operator_packet(data_dir: Path, report_dir: Path) -> SourceQAOperatorPacket:
    worksheet = SourceQAOperatorItem(
        item_type="worksheet_metadata",
        item_id="data_vendor_or_broker",
        target=str(data_dir / "data_source_qa_evidence_worksheet.csv"),
        current_state="missing",
        answer_required="Fill the value from the real vendor/export record.",
        evidence_required="Exact vendor, broker, or terminal data source name.",
        acceptable_evidence="Vendor/export metadata.",
        unacceptable_evidence="Placeholders or generated examples.",
        command_after_completion=FILL_WORKSHEET_COMMAND,
    )
    attachment = SourceQAOperatorItem(
        item_type="attachment",
        item_id="source_identity",
        target=str(data_dir / "source_qa_evidence" / "source_identity_receipt.png"),
        current_state="missing",
        answer_required="Add a retained local evidence file; do not type an answer in this packet.",
        evidence_required="Filled source metadata or vendor export receipt.",
        acceptable_evidence="Retained source identity evidence.",
        unacceptable_evidence="generated receipts",
        command_after_completion=STRICT_MANIFEST_COMMAND,
    )
    return SourceQAOperatorPacket(
        decision="BLOCK",
        as_of="2026-06-10",
        data_dir=str(data_dir),
        report_dir=str(report_dir),
        worksheet_path=str(data_dir / "data_source_qa_evidence_worksheet.csv"),
        evidence_dir=str(data_dir / "source_qa_evidence"),
        dropzone_kit=_dropzone_kit(data_dir),
        missing_worksheet_count=1,
        missing_attachment_count=1,
        items=[worksheet, attachment],
        command_sequence=[FILL_WORKSHEET_COMMAND, STRICT_MANIFEST_COMMAND],
        acceptance_criteria=["Source QA evidence is complete."],
        prohibited_actions=OPERATOR_PROHIBITED_ACTIONS,
    )


def _pass_operator_packet(data_dir: Path, report_dir: Path) -> SourceQAOperatorPacket:
    return SourceQAOperatorPacket(
        decision="PASS",
        as_of="2026-06-10",
        data_dir=str(data_dir),
        report_dir=str(report_dir),
        worksheet_path=str(data_dir / "data_source_qa_evidence_worksheet.csv"),
        evidence_dir=str(data_dir / "source_qa_evidence"),
        dropzone_kit=_dropzone_kit(data_dir),
        missing_worksheet_count=0,
        missing_attachment_count=0,
        items=[],
        command_sequence=[],
        acceptance_criteria=["Source QA evidence is complete."],
        prohibited_actions=OPERATOR_PROHIBITED_ACTIONS,
    )


def _blocked_inbox(data_dir: Path, report_dir: Path) -> SourceQAEvidenceInboxReport:
    item = SourceQAEvidenceInboxItem(
        item_id="source_identity",
        target_path=str(data_dir / "source_qa_evidence" / "source_identity_receipt.png"),
        current_state="missing",
        required_evidence="Vendor export receipt.",
        acceptable_evidence="Retained source identity evidence.",
        unacceptable_evidence="generated receipts",
        matched_files=[],
        suggested_files=[],
        status="BLOCK",
        message="Required source QA evidence attachment is missing from the inbox.",
        next_command=STRICT_MANIFEST_COMMAND,
    )
    return SourceQAEvidenceInboxReport(
        status="BLOCK",
        as_of="2026-06-10",
        data_dir=str(data_dir),
        report_dir=str(report_dir),
        checklist_path=str(data_dir / "data_source_qa.json"),
        evidence_dir=str(data_dir / "source_qa_evidence"),
        manifest_path=str(data_dir / "source_qa_evidence_manifest.json"),
        scanned_file_count=0,
        required_item_count=1,
        matched_item_count=0,
        missing_item_count=1,
        invalid_file_count=0,
        unmatched_file_count=0,
        worksheet_fill_command=FILL_WORKSHEET_COMMAND,
        worksheet_fill_command_ready=False,
        worksheet_fill_command_status="BLOCK",
        worksheet_fill_command_blockers=["source_identity: target_path value is not ready evidence."],
        worksheet_fill_command_warnings=[],
        worksheet_fill_args=[
            SourceQAWorksheetFillArgument(
                item_id="source_identity",
                cli_argument="--source-identity-evidence",
                value=str(data_dir / "source_qa_evidence" / "source_identity_receipt.png"),
                source="target_path",
                exists=False,
                ready=False,
                status="BLOCK",
                message="No matching local evidence file is available yet.",
            )
        ],
        items=[item],
        unmatched_files=[],
        next_commands=[STRICT_MANIFEST_COMMAND],
        next_actions=["Add retained local evidence files for missing source QA ids: source_identity."],
        prohibited_actions=[],
    )


def _pass_inbox(data_dir: Path, report_dir: Path) -> SourceQAEvidenceInboxReport:
    return SourceQAEvidenceInboxReport(
        status="PASS",
        as_of="2026-06-10",
        data_dir=str(data_dir),
        report_dir=str(report_dir),
        checklist_path=str(data_dir / "data_source_qa.json"),
        evidence_dir=str(data_dir / "source_qa_evidence"),
        manifest_path=str(data_dir / "source_qa_evidence_manifest.json"),
        scanned_file_count=5,
        required_item_count=5,
        matched_item_count=5,
        missing_item_count=0,
        invalid_file_count=0,
        unmatched_file_count=0,
        worksheet_fill_command=FILL_WORKSHEET_COMMAND,
        worksheet_fill_command_ready=True,
        worksheet_fill_command_status="PASS",
        worksheet_fill_command_blockers=[],
        worksheet_fill_command_warnings=[],
        worksheet_fill_args=[],
        items=[],
        unmatched_files=[],
        next_commands=[],
        next_actions=[],
        prohibited_actions=[],
    )


def _dropzone_kit(data_dir: Path) -> SourceQAEvidenceDropzoneKit:
    return SourceQAEvidenceDropzoneKit(
        evidence_dir=str(data_dir / "source_qa_evidence"),
        readme_path=str(data_dir / "source_qa_evidence" / "README_source_qa_evidence_dropzone.md"),
        worksheet_path=str(data_dir / "data_source_qa_evidence_worksheet.csv"),
        manifest_path=str(data_dir / "source_qa_evidence_manifest.json"),
        answers_path=str(data_dir / "data_source_qa_answers.json"),
        required_files=[],
        checklist=[],
        command_sequence=[],
        prohibited_actions=OPERATOR_PROHIBITED_ACTIONS,
    )


def _blocked_readiness(data_dir: Path, report_dir: Path) -> SourceQAEvidenceReadiness:
    return SourceQAEvidenceReadiness(
        status="BLOCK",
        checklist_path=str(data_dir / "data_source_qa.json"),
        worksheet_path=str(data_dir / "data_source_qa_evidence_worksheet.csv"),
        answers_path=str(data_dir / "data_source_qa_answers.json"),
        evidence_manifest_path=str(data_dir / "source_qa_evidence_manifest.json"),
        require_evidence_manifest=True,
        sections=[
            SourceQAEvidenceReadinessSection(
                name="worksheet_preflight",
                status="BLOCK",
                artifact=str(data_dir / "data_source_qa_evidence_worksheet.csv"),
                summary="rows=0, findings=1",
                blockers=["data_vendor_or_broker: answer is missing."],
                next_command=FILL_WORKSHEET_COMMAND,
            ),
            SourceQAEvidenceReadinessSection(
                name="strict_source_qa_review",
                status="BLOCK",
                artifact=str(report_dir / "source_qa" / "data_source_qa_review.json"),
                summary="findings=1",
                blockers=["SOURCE_QA_MISSING: source identity evidence is missing."],
            ),
        ],
        next_commands=[FILL_WORKSHEET_COMMAND],
        prohibited_actions=[],
    )


def _pass_readiness(data_dir: Path, report_dir: Path) -> SourceQAEvidenceReadiness:
    return SourceQAEvidenceReadiness(
        status="PASS",
        checklist_path=str(data_dir / "data_source_qa.json"),
        worksheet_path=str(data_dir / "data_source_qa_evidence_worksheet.csv"),
        answers_path=str(data_dir / "data_source_qa_answers.json"),
        evidence_manifest_path=str(data_dir / "source_qa_evidence_manifest.json"),
        require_evidence_manifest=True,
        sections=[
            SourceQAEvidenceReadinessSection(
                name="strict_source_qa_review",
                status="PASS",
                artifact=str(report_dir / "source_qa" / "data_source_qa_review.json"),
                summary="findings=0",
                blockers=[],
            ),
        ],
        next_commands=[],
        prohibited_actions=[],
    )


def _touch_required_artifacts(data_dir: Path, report_dir: Path) -> None:
    paths = [
        report_dir / "source_qa_operator_packet.json",
        report_dir / "source_qa_evidence_inbox.json",
        report_dir / "source_qa" / "source_qa_evidence_readiness.json",
        report_dir / "source_qa" / "data_source_qa_review.json",
        data_dir / "data_source_qa.json",
        data_dir / "data_source_qa_evidence_worksheet.csv",
        data_dir / "data_source_qa_answers.json",
        data_dir / "source_qa_evidence_manifest.json",
        data_dir / "source_qa_evidence" / ".keep",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
