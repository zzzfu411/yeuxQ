from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from quantify.data.source_qa import (
    build_data_source_qa,
    build_data_source_qa_answers,
    build_data_source_qa_answers_from_evidence_worksheet,
    build_data_source_qa_evidence_worksheet,
    build_data_source_qa_evidence_worksheet_preflight,
    build_data_source_qa_review,
    build_source_qa_evidence_manifest,
    build_source_qa_evidence_manifest_preflight,
    write_data_source_qa,
    write_data_source_qa_answers,
    write_data_source_qa_evidence_worksheet,
    write_data_source_qa_evidence_worksheet_preflight,
    write_data_source_qa_review,
    write_source_qa_evidence_manifest,
    write_source_qa_evidence_manifest_preflight,
)


def test_build_data_source_qa_reads_recent_config(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    _write_config(config)

    checklist = build_data_source_qa(
        config_path=config,
        output_dir=tmp_path / "data_exports",
        as_of="2026-06-08",
    )
    out = write_data_source_qa(checklist, tmp_path / "data_exports")

    assert checklist.start == "2024-06-03"
    assert checklist.end == "2026-06-05"
    assert checklist.as_of == "2026-06-08"
    assert checklist.price_adjustment == "qfq"
    assert checklist.universe["mode"] == "all_a"
    assert checklist.universe["index_code"] == "000906"
    assert any(item.id == "point_in_time" and item.severity == "BLOCK_IF_NO" for item in checklist.checklist)
    assert any(item["file_name"] == "bars.csv" and item["required"] for item in checklist.expected_files)
    assert (out / "data_source_qa.json").exists()
    assert (out / "data_source_qa_answers_template.json").exists()
    assert (out / "data_source_qa_evidence_worksheet.json").exists()
    assert (out / "data_source_qa_evidence_worksheet.csv").exists()
    assert (out / "data_source_qa_evidence_worksheet.md").exists()
    markdown = (out / "data_source_qa.md").read_text(encoding="utf-8")
    assert "A-share Data Source QA Checklist" in markdown
    assert "not a trading signal" in markdown
    assert "BLOCK_IF_NO" in markdown
    template = json.loads((out / "data_source_qa_answers_template.json").read_text(encoding="utf-8"))
    assert template["answers"]["price_adjustment"]["required_evidence"]
    assert template["answers"]["price_adjustment"]["evidence"] == ""


def test_data_source_qa_review_blocks_missing_answers(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)

    review = build_data_source_qa_review(
        checklist_path=output / "data_source_qa.json",
        answers_path=output / "data_source_qa_answers.json",
    )
    out = write_data_source_qa_review(review, tmp_path / "review")

    assert review.status == "BLOCK"
    assert any(finding.code == "SOURCE_QA_ANSWERS_MISSING" for finding in review.findings)
    missing = next(finding for finding in review.findings if finding.code == "SOURCE_QA_ANSWERS_MISSING")
    assert missing.evidence["target"].endswith("data_source_qa_evidence_worksheet.csv")
    assert "required_evidence" in missing.evidence
    assert (out / "data_source_qa_review.json").exists()


def test_data_source_qa_evidence_worksheet_maps_required_source_fields(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)

    worksheet = build_data_source_qa_evidence_worksheet(
        checklist_path=output / "data_source_qa.json",
        output_dir=output,
    )
    out = write_data_source_qa_evidence_worksheet(worksheet, output)
    rows = [row.to_dict() for row in worksheet.rows]
    by_id = {row["field_or_question_id"]: row for row in rows}
    csv_text = (out / "data_source_qa_evidence_worksheet.csv").read_text(encoding="utf-8-sig")
    md_text = (out / "data_source_qa_evidence_worksheet.md").read_text(encoding="utf-8")

    assert by_id["data_vendor_or_broker"]["cli_argument"] == "--vendor"
    assert by_id["source_identity"]["cli_argument"] == "--vendor/--terminal/--operator/--exported-at"
    assert by_id["price_adjustment"]["cli_argument"] == "--price-adjustment-evidence"
    assert by_id["license_scope"]["cli_argument"] == "--license-evidence"
    assert by_id["point_in_time"]["cli_argument"] == "--point-in-time-evidence"
    assert by_id["manual_signoff"]["cli_argument"] == "--reviewed-by/--reviewed-at"
    assert by_id["source_identity"]["answer"] == ""
    assert by_id["source_identity"]["evidence"] == ""
    assert "data_vendor_or_broker" in csv_text
    assert "write_data_source_qa_answers.py" in md_text
    commands = "\n".join(worksheet.workflow_commands)
    assert "fill_data_source_qa_evidence_worksheet.py" in commands
    assert commands.index("fill_data_source_qa_evidence_worksheet.py") < commands.index(
        "run_data_source_qa_worksheet_preflight.py"
    )
    assert "--require-evidence-manifest" in "\n".join(worksheet.workflow_commands)
    assert (out / "data_source_qa_evidence_worksheet.json").exists()


def test_data_source_qa_review_passes_complete_answers(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    _write_complete_answers(output / "data_source_qa_answers.json", checklist.to_dict())

    review = build_data_source_qa_review(
        checklist_path=output / "data_source_qa.json",
        answers_path=output / "data_source_qa_answers.json",
    )

    assert review.status == "PASS"
    assert review.findings == []


def test_source_review_ignores_csv_validation_questions(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    _write_source_answers(output / "data_source_qa_answers.json", checklist.to_dict())

    review = build_data_source_qa_review(
        checklist_path=output / "data_source_qa.json",
        answers_path=output / "data_source_qa_answers.json",
        review_stage="source",
    )

    assert review.status == "PASS"
    assert review.findings == []


def test_write_data_source_qa_answers_passes_source_review(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)

    answers = build_data_source_qa_answers(
        checklist_path=output / "data_source_qa.json",
        data_vendor_or_broker="unit-test vendor",
        terminal_or_product_name="unit-test terminal",
        export_operator="tester",
        exported_at_local_time="2026-06-08 09:00:00",
        price_adjustment="qfq",
        price_adjustment_evidence="vendor export setting says qfq",
        license_or_usage_scope="research and paper trading only",
        license_evidence="unit-test license note",
        point_in_time_evidence="fundamentals and constituents are PIT snapshots",
        reviewed_by="tester",
        reviewed_at="2026-06-08",
    )
    write_data_source_qa_answers(answers, output / "data_source_qa_answers.json")

    review = build_data_source_qa_review(
        checklist_path=output / "data_source_qa.json",
        answers_path=output / "data_source_qa_answers.json",
        review_stage="source",
    )

    assert review.status == "PASS"
    assert answers["answers"]["source_identity"]["answer"] == "yes"
    assert answers["answers"]["symbol_breadth"]["answer"] == ""


def test_source_qa_evidence_manifest_strict_review_passes_with_attachments(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    evidence_dir = output / "source_qa_evidence"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    _write_source_answers(output / "data_source_qa_answers.json", checklist.to_dict())
    for item in checklist.checklist:
        if item.review_stage == "source" and item.severity == "BLOCK_IF_NO":
            _write_evidence_file(evidence_dir / f"{item.id}_evidence.txt", item.id)
    manifest = build_source_qa_evidence_manifest(
        checklist_path=output / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, output)

    review = build_data_source_qa_review(
        checklist_path=output / "data_source_qa.json",
        answers_path=output / "data_source_qa_answers.json",
        evidence_manifest_path=output / "source_qa_evidence_manifest.json",
        require_evidence_manifest=True,
    )

    assert review.status == "PASS"
    assert review.evidence_manifest_path == str(output / "source_qa_evidence_manifest.json")
    assert review.require_evidence_manifest is True
    assert {item.id for item in manifest.items}.issuperset(
        {"source_identity", "license_scope", "price_adjustment", "point_in_time", "manual_signoff"}
    )


def test_source_qa_evidence_manifest_preflight_passes_with_required_attachments(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    evidence_dir = output / "source_qa_evidence"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    for item in checklist.checklist:
        if item.review_stage == "source" and item.severity == "BLOCK_IF_NO":
            _write_evidence_file(evidence_dir / f"{item.id}_evidence.txt", item.id)
    manifest = build_source_qa_evidence_manifest(
        checklist_path=output / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, output)

    report = build_source_qa_evidence_manifest_preflight(
        checklist_path=output / "data_source_qa.json",
        manifest_path=output / "source_qa_evidence_manifest.json",
        evidence_dir=evidence_dir,
    )
    out = write_source_qa_evidence_manifest_preflight(report, output)
    payload = json.loads(
        (out / "source_qa_evidence_manifest_preflight.json").read_text(encoding="utf-8")
    )

    assert report.status == "PASS"
    assert report.missing_required_ids == []
    assert payload["status"] == "PASS"
    assert (out / "source_qa_evidence_manifest_preflight.md").exists()


def test_source_qa_evidence_manifest_preflight_blocks_missing_required_attachments(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    evidence_dir = output / "source_qa_evidence"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    _write_evidence_file(evidence_dir / "source_identity_evidence.txt", "source_identity")
    manifest = build_source_qa_evidence_manifest(
        checklist_path=output / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, output)

    report = build_source_qa_evidence_manifest_preflight(
        checklist_path=output / "data_source_qa.json",
        manifest_path=output / "source_qa_evidence_manifest.json",
        evidence_dir=evidence_dir,
    )
    codes = {finding.code for finding in report.findings}

    assert report.status == "BLOCK"
    assert "SOURCE_QA_EVIDENCE_ATTACHMENT_MISSING" in codes
    assert "license_scope" in report.missing_required_ids
    assert "source_identity" in report.valid_required_ids


def test_source_qa_evidence_manifest_allows_named_real_evidence_files(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    evidence_dir = output / "source_qa_evidence"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    _write_source_answers(output / "data_source_qa_answers.json", checklist.to_dict())
    evidence_files = {
        "source_identity_receipt.png": b"\x89PNG\r\nretained terminal screenshot metadata\n",
        "license_scope_note.pdf": b"%PDF-1.4\nretained license scope document\n%%EOF\n",
        "price_adjustment_qfq.png": b"\x89PNG\r\nretained qfq setting screenshot metadata\n",
        "point_in_time_note.md": (
            "PIT review note: OHLCV export excludes non-point-in-time fundamentals."
        ).encode(),
        "manual_signoff.md": (
            "Manual review note: tester checked retained vendor export evidence on 2026-06-08."
        ).encode(),
    }
    for name, content in evidence_files.items():
        path = evidence_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest = build_source_qa_evidence_manifest(
        checklist_path=output / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, output)

    review = build_data_source_qa_review(
        checklist_path=output / "data_source_qa.json",
        answers_path=output / "data_source_qa_answers.json",
        evidence_manifest_path=output / "source_qa_evidence_manifest.json",
        require_evidence_manifest=True,
    )

    assert review.status == "PASS"
    assert review.findings == []


def test_source_qa_evidence_manifest_strict_review_blocks_missing_attachment(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    evidence_dir = output / "source_qa_evidence"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    _write_source_answers(output / "data_source_qa_answers.json", checklist.to_dict())
    _write_evidence_file(evidence_dir / "source_identity_evidence.txt", "source_identity")
    manifest = build_source_qa_evidence_manifest(
        checklist_path=output / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, output)

    review = build_data_source_qa_review(
        checklist_path=output / "data_source_qa.json",
        answers_path=output / "data_source_qa_answers.json",
        evidence_manifest_path=output / "source_qa_evidence_manifest.json",
        require_evidence_manifest=True,
    )
    codes = {finding.code for finding in review.findings}

    assert review.status == "BLOCK"
    assert "SOURCE_QA_EVIDENCE_ATTACHMENT_MISSING" in codes
    finding = next(
        finding
        for finding in review.findings
        if finding.code == "SOURCE_QA_EVIDENCE_ATTACHMENT_MISSING"
    )
    assert finding.evidence["attachment_id"]
    assert finding.evidence["question"]
    assert finding.evidence["required_evidence"]
    assert finding.evidence["target"].endswith("_evidence.txt") or "source_qa_evidence" in finding.evidence["target"]
    assert finding.evidence["evidence_manifest_path"] == str(output / "source_qa_evidence_manifest.json")
    assert review.status == "BLOCK"


def test_source_qa_evidence_manifest_blocks_hash_mismatch(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    evidence_dir = output / "source_qa_evidence"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    _write_source_answers(output / "data_source_qa_answers.json", checklist.to_dict())
    path = evidence_dir / "source_identity_evidence.txt"
    _write_evidence_file(path, "source_identity")
    manifest = build_source_qa_evidence_manifest(
        checklist_path=output / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, output)
    path.write_text("changed after manifest", encoding="utf-8")

    review = build_data_source_qa_review(
        checklist_path=output / "data_source_qa.json",
        answers_path=output / "data_source_qa_answers.json",
        evidence_manifest_path=output / "source_qa_evidence_manifest.json",
    )

    assert review.status == "BLOCK"
    finding = next(
        finding
        for finding in review.findings
        if finding.code == "SOURCE_QA_EVIDENCE_ATTACHMENT_HASH_MISMATCH"
    )
    assert finding.evidence["attachment_id"] == "source_identity"
    assert finding.evidence["path"] == str(path)
    assert finding.evidence["target"] == str(path)
    assert finding.evidence["invalid_attachment_reason"] == "sha256_mismatch"
    assert finding.evidence["expected"]
    assert finding.evidence["actual"]


def test_source_qa_evidence_manifest_blocks_placeholder_attachment_content(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    evidence_dir = output / "source_qa_evidence"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    _write_source_answers(output / "data_source_qa_answers.json", checklist.to_dict())
    for item in checklist.checklist:
        if item.review_stage == "source" and item.severity == "BLOCK_IF_NO":
            path = evidence_dir / f"{item.id}_evidence.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"sample evidence for {item.id}", encoding="utf-8")
    manifest = build_source_qa_evidence_manifest(
        checklist_path=output / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, output)

    review = build_data_source_qa_review(
        checklist_path=output / "data_source_qa.json",
        answers_path=output / "data_source_qa_answers.json",
        evidence_manifest_path=output / "source_qa_evidence_manifest.json",
        require_evidence_manifest=True,
    )
    placeholder_findings = [
        finding
        for finding in review.findings
        if finding.code == "SOURCE_QA_EVIDENCE_ATTACHMENT_PLACEHOLDER"
    ]

    assert review.status == "BLOCK"
    assert placeholder_findings
    assert {finding.evidence["invalid_attachment_reason"] for finding in placeholder_findings} == {
        "placeholder_content"
    }
    assert any("sample" in finding.evidence["placeholder_reason"] for finding in placeholder_findings)


def test_source_qa_evidence_manifest_blocks_generated_attachment_path(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    evidence_dir = output / "source_qa_evidence"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    _write_source_answers(output / "data_source_qa_answers.json", checklist.to_dict())
    for item in checklist.checklist:
        if item.review_stage != "source" or item.severity != "BLOCK_IF_NO":
            continue
        file_name = "source_identity_worksheet.txt" if item.id == "source_identity" else f"{item.id}_evidence.txt"
        _write_evidence_file(evidence_dir / file_name, item.id)
    manifest = build_source_qa_evidence_manifest(
        checklist_path=output / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, output)

    review = build_data_source_qa_review(
        checklist_path=output / "data_source_qa.json",
        answers_path=output / "data_source_qa_answers.json",
        evidence_manifest_path=output / "source_qa_evidence_manifest.json",
        require_evidence_manifest=True,
    )
    finding = next(
        finding
        for finding in review.findings
        if finding.code == "SOURCE_QA_EVIDENCE_ATTACHMENT_PLACEHOLDER"
    )

    assert review.status == "BLOCK"
    assert finding.evidence["attachment_id"] == "source_identity"
    assert finding.evidence["invalid_attachment_reason"] == "generated_artifact_path"
    assert "worksheet" in finding.evidence["placeholder_reason"]
    assert "worksheet" in finding.evidence["path_reason"]
    assert finding.evidence["path"].endswith("source_identity_worksheet.txt")


def test_source_qa_evidence_manifest_blocks_generated_attachment_plan_path(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    evidence_dir = output / "source_qa_evidence"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    _write_source_answers(output / "data_source_qa_answers.json", checklist.to_dict())
    for item in checklist.checklist:
        if item.review_stage != "source" or item.severity != "BLOCK_IF_NO":
            continue
        _write_evidence_file(evidence_dir / f"{item.id}_evidence.txt", item.id)
    plan_path = evidence_dir / "source_qa_evidence_attachment_plan.csv"
    plan_path.write_text("id,suggested_file\nsource_identity,source_identity_receipt.png\n", encoding="utf-8")
    manifest = build_source_qa_evidence_manifest(
        checklist_path=output / "data_source_qa.json",
        evidence_dir=evidence_dir,
    ).to_dict()
    manifest["items"].append(
        {
            "id": "source_identity",
            "path": str(plan_path),
            "sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            "size_bytes": plan_path.stat().st_size,
            "modified_at_utc": "2026-06-08T00:00:00+00:00",
        }
    )
    (output / "source_qa_evidence_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    review = build_data_source_qa_review(
        checklist_path=output / "data_source_qa.json",
        answers_path=output / "data_source_qa_answers.json",
        evidence_manifest_path=output / "source_qa_evidence_manifest.json",
        require_evidence_manifest=True,
    )
    finding = next(
        finding
        for finding in review.findings
        if finding.code == "SOURCE_QA_EVIDENCE_ATTACHMENT_PLACEHOLDER"
        and finding.evidence["path"] == str(plan_path)
    )

    assert review.status == "BLOCK"
    assert finding.evidence["invalid_attachment_reason"] == "generated_artifact_path"
    assert finding.evidence["path_reason"] == "generated_workflow_file:source-qa-evidence-attachment-plan"


def test_build_answers_from_filled_evidence_worksheet_passes_source_review(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    worksheet = build_data_source_qa_evidence_worksheet(
        checklist_path=output / "data_source_qa.json",
        output_dir=output,
    )
    filled = {
        "data_vendor_or_broker": "unit-test vendor",
        "terminal_or_product_name": "unit-test terminal",
        "export_operator": "tester",
        "exported_at_local_time": "2026-06-08 09:00:00",
        "price_adjustment": "qfq",
        "license_or_usage_scope": "research and paper trading only",
        "reviewed_by": "tester",
        "reviewed_at": "2026-06-08",
        "license_scope": "vendor account terms allow local research use",
        "price_adjustment_evidence": "vendor export setting screen shows qfq adjustment",
        "point_in_time": "OHLCV-only export; non-PIT fundamentals excluded from candidates",
    }
    rows = []
    for row in worksheet.rows:
        payload = row.to_dict()
        key = payload["field_or_question_id"]
        if key in filled:
            payload["answer"] = filled[key]
        if payload["row_type"] == "source_question":
            payload["answer"] = "yes"
            evidence_key = "price_adjustment_evidence" if key == "price_adjustment" else key
            payload["evidence"] = filled.get(evidence_key, f"source evidence for {key}")
        rows.append(payload)
    _write_worksheet_csv(output / "filled_worksheet.csv", rows)

    answers = build_data_source_qa_answers_from_evidence_worksheet(
        checklist_path=output / "data_source_qa.json",
        worksheet_path=output / "filled_worksheet.csv",
    )
    write_data_source_qa_answers(answers, output / "data_source_qa_answers.json")
    review = build_data_source_qa_review(
        checklist_path=output / "data_source_qa.json",
        answers_path=output / "data_source_qa_answers.json",
    )

    assert review.status == "PASS"
    assert answers["source_metadata"]["data_vendor_or_broker"] == "unit-test vendor"
    assert answers["answers"]["price_adjustment"]["evidence"] == (
        "vendor export setting screen shows qfq adjustment"
    )
    assert answers["answers"]["symbol_breadth"]["answer"] == ""


def test_data_source_qa_evidence_worksheet_preflight_passes_filled_rows(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    worksheet = build_data_source_qa_evidence_worksheet(
        checklist_path=output / "data_source_qa.json",
        output_dir=output,
    )
    rows = _filled_worksheet_rows(worksheet)
    _write_worksheet_csv(output / "filled_worksheet.csv", rows)

    report = build_data_source_qa_evidence_worksheet_preflight(
        checklist_path=output / "data_source_qa.json",
        worksheet_path=output / "filled_worksheet.csv",
    )
    out = write_data_source_qa_evidence_worksheet_preflight(report, output)
    payload = json.loads((out / "data_source_qa_worksheet_preflight.json").read_text(encoding="utf-8"))

    assert report.status == "PASS"
    assert report.findings == []
    assert payload["status"] == "PASS"
    assert "write_data_source_qa_answers.py" in "\n".join(payload["next_commands"])
    assert (out / "data_source_qa_worksheet_preflight.md").exists()


def test_data_source_qa_evidence_worksheet_preflight_blocks_placeholders_and_generated_paths(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    worksheet = build_data_source_qa_evidence_worksheet(
        checklist_path=output / "data_source_qa.json",
        output_dir=output,
    )
    rows = []
    for row in worksheet.rows:
        payload = row.to_dict()
        if payload["row_type"] == "metadata":
            payload["answer"] = "<placeholder>"
            payload["evidence"] = "data_source_qa_evidence_worksheet.csv"
        if payload["row_type"] == "source_question":
            payload["answer"] = "yes"
            payload["evidence"] = "source_qa_evidence_attachment_plan.csv"
        rows.append(payload)
    _write_worksheet_csv(output / "placeholder_worksheet.csv", rows)

    report = build_data_source_qa_evidence_worksheet_preflight(
        checklist_path=output / "data_source_qa.json",
        worksheet_path=output / "placeholder_worksheet.csv",
    )
    codes = {finding.code for finding in report.findings}

    assert report.status == "BLOCK"
    assert "SOURCE_QA_WORKSHEET_METADATA_PLACEHOLDER" in codes
    assert "SOURCE_QA_WORKSHEET_GENERATED_EVIDENCE_REFERENCE" in codes
    assert any(
        "generated_workflow_file:source-qa-evidence-attachment-plan" in str(finding.evidence)
        for finding in report.findings
    )


def test_data_source_qa_evidence_worksheet_preflight_blocks_deleted_required_rows(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    worksheet = build_data_source_qa_evidence_worksheet(
        checklist_path=output / "data_source_qa.json",
        output_dir=output,
    )
    rows = [
        row
        for row in _filled_worksheet_rows(worksheet)
        if row["field_or_question_id"] != "point_in_time"
    ]
    _write_worksheet_csv(output / "missing_row_worksheet.csv", rows)

    report = build_data_source_qa_evidence_worksheet_preflight(
        checklist_path=output / "data_source_qa.json",
        worksheet_path=output / "missing_row_worksheet.csv",
    )
    missing = next(
        finding
        for finding in report.findings
        if finding.code == "SOURCE_QA_WORKSHEET_REQUIRED_SOURCE_ROW_MISSING"
    )

    assert report.status == "BLOCK"
    assert missing.field_or_question_id == "point_in_time"


def test_build_answers_from_placeholder_worksheet_still_blocks(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    worksheet = build_data_source_qa_evidence_worksheet(
        checklist_path=output / "data_source_qa.json",
        output_dir=output,
    )
    rows = []
    for row in worksheet.rows:
        payload = row.to_dict()
        if payload["row_type"] == "metadata":
            payload["answer"] = "<placeholder>"
        if payload["row_type"] == "source_question":
            payload["answer"] = "yes"
            payload["evidence"] = "<evidence>"
        rows.append(payload)
    _write_worksheet_csv(output / "placeholder_worksheet.csv", rows)

    answers = build_data_source_qa_answers_from_evidence_worksheet(
        checklist_path=output / "data_source_qa.json",
        worksheet_path=output / "placeholder_worksheet.csv",
    )
    write_data_source_qa_answers(answers, output / "data_source_qa_answers.json")
    review = build_data_source_qa_review(
        checklist_path=output / "data_source_qa.json",
        answers_path=output / "data_source_qa_answers.json",
    )
    codes = {finding.code for finding in review.findings}

    assert review.status == "BLOCK"
    assert "SOURCE_METADATA_PLACEHOLDER" in codes
    assert "SOURCE_QA_EVIDENCE_PLACEHOLDER" in codes


def test_data_source_qa_review_blocks_placeholder_metadata_and_evidence(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)

    answers = build_data_source_qa_answers(
        checklist_path=output / "data_source_qa.json",
        data_vendor_or_broker="<vendor-or-broker>",
        terminal_or_product_name="<terminal-name>",
        export_operator="<operator>",
        exported_at_local_time="<local-time>",
        price_adjustment="qfq",
        price_adjustment_evidence="<evidence>",
        license_or_usage_scope="research and paper trading only",
        license_evidence="<evidence>",
        point_in_time_evidence="<evidence-or-non-pit-note>",
        reviewed_by="<name>",
        reviewed_at="<date>",
    )
    write_data_source_qa_answers(answers, output / "data_source_qa_answers.json")

    review = build_data_source_qa_review(
        checklist_path=output / "data_source_qa.json",
        answers_path=output / "data_source_qa_answers.json",
        review_stage="source",
    )
    codes = {finding.code for finding in review.findings}

    assert review.status == "BLOCK"
    assert "SOURCE_METADATA_PLACEHOLDER" in codes
    assert "SOURCE_QA_EVIDENCE_PLACEHOLDER" in codes
    placeholder_finding = next(
        finding for finding in review.findings if finding.code == "SOURCE_METADATA_PLACEHOLDER"
    )
    assert "data_vendor_or_broker" in placeholder_finding.evidence["placeholder_metadata"]


def test_csv_validation_review_uses_validation_report(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    validation = tmp_path / "csv_validation.json"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    _write_source_answers(output / "data_source_qa_answers.json", checklist.to_dict())
    _write_validation_report(validation, symbols=300)

    review = build_data_source_qa_review(
        checklist_path=output / "data_source_qa.json",
        answers_path=output / "data_source_qa_answers.json",
        review_stage="csv_validation",
        validation_report_path=validation,
    )

    assert review.status == "PASS"
    assert review.findings == []


def test_csv_validation_review_blocks_low_symbol_count(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    validation = tmp_path / "csv_validation.json"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    _write_source_answers(output / "data_source_qa_answers.json", checklist.to_dict())
    _write_validation_report(validation, symbols=10)

    review = build_data_source_qa_review(
        checklist_path=output / "data_source_qa.json",
        answers_path=output / "data_source_qa_answers.json",
        review_stage="csv_validation",
        validation_report_path=validation,
    )

    assert review.status == "BLOCK"
    assert any(
        finding.code == "SOURCE_QA_BLOCK_ANSWER"
        and finding.evidence.get("id") == "symbol_breadth"
        for finding in review.findings
    )


def test_write_data_source_qa_cli_writes_outputs(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/write_data_source_qa.py",
            "--config",
            str(config),
            "--output-dir",
            str(output),
            "--min-symbols",
            "300",
            "--as-of",
            "2026-06-08",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output / "data_source_qa.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["start"] == "2024-06-03"
    assert payload["as_of"] == "2026-06-08"
    assert payload["source_metadata_template"]["license_or_usage_scope"] == "research and paper trading only"
    assert "run_source_qa_preflight.py" in "\n".join(payload["workflow_commands"])
    assert "write_data_source_qa_evidence_worksheet.py" in "\n".join(payload["workflow_commands"])
    assert "--require-evidence-manifest" in "\n".join(payload["workflow_commands"])
    assert "run_offline_data_intake.py" in "\n".join(payload["workflow_commands"])
    assert (output / "data_source_qa.md").exists()
    assert (output / "data_source_qa_evidence_worksheet.csv").exists()


def test_run_data_source_qa_review_cli_returns_nonzero_on_block(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    review_dir = tmp_path / "review"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_data_source_qa_review.py",
            "--checklist",
            str(output / "data_source_qa.json"),
            "--answers",
            str(output / "data_source_qa_answers.json"),
            "--output-dir",
            str(review_dir),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((review_dir / "data_source_qa_review.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["status"] == "BLOCK"
    assert any(item["code"] == "SOURCE_QA_ANSWERS_MISSING" for item in payload["findings"])


def test_write_source_qa_evidence_manifest_cli_writes_outputs(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    evidence_dir = output / "source_qa_evidence"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    _write_evidence_file(evidence_dir / "license_scope_receipt.txt", "license_scope")

    completed = subprocess.run(
        [
            sys.executable,
            "examples/write_source_qa_evidence_manifest.py",
            "--checklist",
            str(output / "data_source_qa.json"),
            "--evidence-dir",
            str(evidence_dir),
            "--output-dir",
            str(output),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output / "source_qa_evidence_manifest.json").read_text(encoding="utf-8"))
    preflight = json.loads(
        (output / "source_qa_evidence_manifest_preflight.json").read_text(encoding="utf-8")
    )
    assert completed.returncode == 0
    assert payload["manifest_type"] == "source_qa_evidence_manifest"
    assert payload["items"][0]["id"] == "license_scope"
    assert any("--strict" in command for command in preflight["next_commands"])
    assert (output / "source_qa_evidence_manifest.md").exists()
    assert (output / "source_qa_evidence_manifest_preflight.json").exists()
    assert (output / "source_qa_evidence_manifest_preflight.md").exists()


def test_write_source_qa_evidence_manifest_cli_strict_returns_nonzero_on_block(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    evidence_dir = output / "source_qa_evidence"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    _write_evidence_file(evidence_dir / "license_scope_receipt.txt", "license_scope")

    completed = subprocess.run(
        [
            sys.executable,
            "examples/write_source_qa_evidence_manifest.py",
            "--checklist",
            str(output / "data_source_qa.json"),
            "--evidence-dir",
            str(evidence_dir),
            "--output-dir",
            str(output),
            "--strict",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    preflight = json.loads(
        (output / "source_qa_evidence_manifest_preflight.json").read_text(encoding="utf-8")
    )

    assert completed.returncode == 2
    assert preflight["status"] == "BLOCK"
    assert "source_identity" in preflight["missing_required_ids"]


def test_write_data_source_qa_answers_cli_writes_outputs(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/write_data_source_qa_answers.py",
            "--checklist",
            str(output / "data_source_qa.json"),
            "--output",
            str(output / "data_source_qa_answers.json"),
            "--vendor",
            "unit-test vendor",
            "--terminal",
            "unit-test terminal",
            "--operator",
            "tester",
            "--exported-at",
            "2026-06-08 09:00:00",
            "--price-adjustment",
            "qfq",
            "--price-adjustment-evidence",
            "vendor export setting says qfq",
            "--license-evidence",
            "unit-test license note",
            "--point-in-time-evidence",
            "PIT snapshots or non-PIT research-only note",
            "--reviewed-by",
            "tester",
            "--reviewed-at",
            "2026-06-08",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output / "data_source_qa_answers.json").read_text(encoding="utf-8"))
    review = build_data_source_qa_review(
        checklist_path=output / "data_source_qa.json",
        answers_path=output / "data_source_qa_answers.json",
    )
    assert completed.returncode == 0
    assert payload["source_metadata"]["data_vendor_or_broker"] == "unit-test vendor"
    assert review.status == "PASS"


def test_write_data_source_qa_answers_cli_accepts_filled_worksheet(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    worksheet = build_data_source_qa_evidence_worksheet(
        checklist_path=output / "data_source_qa.json",
        output_dir=output,
    )
    rows = []
    for row in worksheet.rows:
        payload = row.to_dict()
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
        key = payload["field_or_question_id"]
        if key in values:
            payload["answer"] = values[key]
            payload["evidence"] = f"vendor export metadata record for {key}"
        if payload["row_type"] == "source_question":
            payload["answer"] = "yes"
            payload["evidence"] = f"real worksheet evidence for {key}"
        rows.append(payload)
    _write_worksheet_csv(output / "filled_worksheet.csv", rows)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/write_data_source_qa_answers.py",
            "--checklist",
            str(output / "data_source_qa.json"),
            "--worksheet",
            str(output / "filled_worksheet.csv"),
            "--output",
            str(output / "data_source_qa_answers.json"),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output / "data_source_qa_answers.json").read_text(encoding="utf-8"))
    review = build_data_source_qa_review(
        checklist_path=output / "data_source_qa.json",
        answers_path=output / "data_source_qa_answers.json",
    )
    assert completed.returncode == 0
    assert payload["source_metadata"]["terminal_or_product_name"] == "unit-test terminal"
    assert review.status == "PASS"


def test_write_data_source_qa_answers_cli_strict_blocks_without_manifest(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/write_data_source_qa_answers.py",
            "--checklist",
            str(output / "data_source_qa.json"),
            "--output",
            str(output / "data_source_qa_answers.json"),
            "--vendor",
            "unit-test vendor",
            "--terminal",
            "unit-test terminal",
            "--operator",
            "tester",
            "--exported-at",
            "2026-06-08 09:00:00",
            "--price-adjustment",
            "qfq",
            "--price-adjustment-evidence",
            "vendor export setting says qfq",
            "--license-evidence",
            "unit-test license note",
            "--point-in-time-evidence",
            "PIT snapshots or non-PIT research-only note",
            "--reviewed-by",
            "tester",
            "--reviewed-at",
            "2026-06-08",
            "--require-evidence-manifest",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    review = json.loads((output / "data_source_qa_review.json").read_text(encoding="utf-8"))

    assert completed.returncode == 2
    assert review["status"] == "BLOCK"
    assert any(item["code"] == "SOURCE_QA_EVIDENCE_MANIFEST_MISSING" for item in review["findings"])
    assert not (output / "data_source_qa_answers.json").exists()
    assert not (output / "data_source_qa_answers.json.tmp").exists()


def test_write_data_source_qa_answers_cli_strict_commits_after_attachment_review(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    evidence_dir = output / "source_qa_evidence"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)
    worksheet = build_data_source_qa_evidence_worksheet(
        checklist_path=output / "data_source_qa.json",
        output_dir=output,
    )
    _write_worksheet_csv(output / "filled_worksheet.csv", _filled_worksheet_rows(worksheet))
    for item in checklist.checklist:
        if item.review_stage == "source" and item.severity == "BLOCK_IF_NO":
            _write_evidence_file(evidence_dir / f"{item.id}_evidence.txt", item.id)
    manifest = build_source_qa_evidence_manifest(
        checklist_path=output / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, output)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/write_data_source_qa_answers.py",
            "--checklist",
            str(output / "data_source_qa.json"),
            "--worksheet",
            str(output / "filled_worksheet.csv"),
            "--output",
            str(output / "data_source_qa_answers.json"),
            "--evidence-manifest",
            str(output / "source_qa_evidence_manifest.json"),
            "--require-evidence-manifest",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    review = json.loads((output / "data_source_qa_review.json").read_text(encoding="utf-8"))
    payload = json.loads((output / "data_source_qa_answers.json").read_text(encoding="utf-8"))

    assert completed.returncode == 0
    assert review["status"] == "PASS"
    assert payload["source_metadata"]["data_vendor_or_broker"] == "unit-test vendor"
    assert not (output / "data_source_qa_answers.json.tmp").exists()


def test_data_source_qa_worksheet_preflight_cli_writes_block_report(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_data_source_qa_worksheet_preflight.py",
            "--checklist",
            str(output / "data_source_qa.json"),
            "--worksheet",
            str(output / "data_source_qa_evidence_worksheet.csv"),
            "--output-dir",
            str(output),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(
        (output / "data_source_qa_worksheet_preflight.json").read_text(encoding="utf-8")
    )

    assert completed.returncode == 2
    assert payload["status"] == "BLOCK"
    assert any(
        finding["code"] == "SOURCE_QA_WORKSHEET_METADATA_MISSING"
        for finding in payload["findings"]
    )


def test_write_data_source_qa_answers_cli_blocks_bad_worksheet_by_default(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/write_data_source_qa_answers.py",
            "--checklist",
            str(output / "data_source_qa.json"),
            "--worksheet",
            str(output / "data_source_qa_evidence_worksheet.csv"),
            "--output",
            str(output / "data_source_qa_answers.json"),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert (output / "data_source_qa_worksheet_preflight.json").exists()
    assert not (output / "data_source_qa_answers.json").exists()


def test_write_data_source_qa_evidence_worksheet_cli_writes_outputs(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)
    checklist = build_data_source_qa(config_path=config, output_dir=output, as_of="2026-06-08")
    write_data_source_qa(checklist, output)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/write_data_source_qa_evidence_worksheet.py",
            "--checklist",
            str(output / "data_source_qa.json"),
            "--output-dir",
            str(output),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads(
        (output / "data_source_qa_evidence_worksheet.json").read_text(encoding="utf-8")
    )
    assert completed.returncode == 0
    assert payload["rows"][0]["row_type"] == "metadata"
    assert any(row["field_or_question_id"] == "source_identity" for row in payload["rows"])
    assert (output / "data_source_qa_evidence_worksheet.csv").exists()


def _write_complete_answers(path: Path, checklist: dict) -> None:
    answers = {
        item["id"]: {
            "answer": "yes",
            "evidence": f"evidence for {item['id']}",
            "notes": "",
        }
        for item in checklist["checklist"]
    }
    payload = {
        "source_metadata": {
            "data_vendor_or_broker": "unit-test vendor",
            "terminal_or_product_name": "unit-test terminal",
            "export_operator": "tester",
            "exported_at_local_time": "2026-06-08 09:00:00",
            "market": "A-share equities",
            "frequency": "daily",
            "date_range": "2024-06-03 to 2026-06-05",
            "price_adjustment": "qfq",
            "encoding": "utf-8-sig",
            "license_or_usage_scope": "research and paper trading only",
            "known_limitations": "none",
            "reviewed_by": "tester",
            "reviewed_at": "2026-06-08",
        },
        "answers": answers,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_worksheet_csv(path: Path, rows: list[dict[str, str]]) -> None:
    import csv

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


def _filled_worksheet_rows(worksheet) -> list[dict[str, str]]:
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
            payload["evidence"] = (
                f"vendor export audit note for {item_id}: retained terminal screenshot "
                "and reviewer signoff."
            )
        rows.append(payload)
    return rows


def _write_evidence_file(path: Path, item_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"vendor export audit note for {item_id}: reviewed terminal screenshot and retained export metadata.",
        encoding="utf-8",
    )


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
            "exported_at_local_time": "2026-06-08 09:00:00",
            "market": "A-share equities",
            "frequency": "daily",
            "date_range": "2024-06-03 to 2026-06-05",
            "price_adjustment": "qfq",
            "encoding": "utf-8-sig",
            "license_or_usage_scope": "research and paper trading only",
            "known_limitations": "none",
            "reviewed_by": "tester",
            "reviewed_at": "2026-06-08",
        },
        "answers": answers,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_validation_report(path: Path, *, symbols: int) -> None:
    payload = {
        "status": "PASS",
        "dataset_fingerprint": "abc123def456",
        "start": "2024-06-03",
        "end": "2026-06-05",
        "min_symbols": 300,
        "metrics": {
            "bars_symbol_count": symbols,
            "bars_start": "2024-06-03",
            "bars_end": "2026-06-05",
        },
        "files": [
            {
                "role": "bars",
                "exists": True,
                "sha256": "a" * 64,
                "columns": ["symbol", "date", "open", "high", "low", "close", "volume", "amount"],
            },
            {
                "role": "calendar",
                "exists": True,
                "sha256": "b" * 64,
                "columns": ["date", "is_open"],
            },
            {
                "role": "suspensions",
                "exists": True,
                "sha256": "c" * 64,
                "columns": ["symbol", "date", "is_suspended"],
            },
            {
                "role": "stock_info",
                "exists": True,
                "sha256": "d" * 64,
                "columns": ["symbol", "name", "exchange", "list_date", "delist_date", "industry", "is_st"],
            },
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
