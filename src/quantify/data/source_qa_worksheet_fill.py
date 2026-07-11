"""Fill source QA evidence worksheets from explicit operator inputs."""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quantify.data.source_qa import (
    SourceQAEvidenceWorksheet,
    SourceQAEvidenceWorksheetPreflightReport,
    SourceQAEvidenceWorksheetRow,
    build_data_source_qa_evidence_worksheet,
    build_data_source_qa_evidence_worksheet_preflight,
    weak_source_evidence,
    write_data_source_qa_evidence_worksheet,
    write_data_source_qa_evidence_worksheet_preflight,
)

WORKSHEET_FIELDNAMES = [
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

REQUIRED_FILL_INPUTS = {
    "vendor": "--vendor",
    "terminal": "--terminal",
    "operator": "--operator",
    "exported_at": "--exported-at",
    "price_adjustment": "--price-adjustment",
    "license_scope": "--license-scope",
    "reviewed_by": "--reviewed-by",
    "reviewed_at": "--reviewed-at",
    "source_identity_evidence": "--source-identity-evidence",
    "license_evidence": "--license-evidence",
    "price_adjustment_evidence": "--price-adjustment-evidence",
    "point_in_time_evidence": "--point-in-time-evidence",
    "manual_signoff_evidence": "--manual-signoff-evidence",
}

PROHIBITED_ACTIONS = [
    "Do not treat this fill report as source QA approval or data evidence.",
    "Do not use placeholders, generated worksheet files, templates, samples, or plans as evidence.",
    "Do not invent vendor, terminal, license, PIT, adjustment, or reviewer details.",
    "Do not generate data_source_qa_answers.json while fill or worksheet preflight is BLOCK.",
    "Do not connect this workflow to real broker order submission.",
]


@dataclass(frozen=True, slots=True)
class SourceQAWorksheetFillReport:
    status: str
    checklist_path: str
    worksheet_path: str
    output_dir: str
    source_rows: str
    row_count: int
    updated_row_count: int
    updated_rows: list[dict[str, str]]
    missing_inputs: list[str]
    preflight_status: str
    preflight_path: str
    next_commands: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checklist_path": self.checklist_path,
            "worksheet_path": self.worksheet_path,
            "output_dir": self.output_dir,
            "source_rows": self.source_rows,
            "row_count": self.row_count,
            "updated_row_count": self.updated_row_count,
            "updated_rows": self.updated_rows,
            "missing_inputs": self.missing_inputs,
            "preflight_status": self.preflight_status,
            "preflight_path": self.preflight_path,
            "next_commands": self.next_commands,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Source QA Worksheet Fill: {self.status}",
            "",
            f"- Checklist: `{self.checklist_path}`",
            f"- Worksheet: `{self.worksheet_path}`",
            f"- Output directory: `{self.output_dir}`",
            f"- Source rows: `{self.source_rows}`",
            f"- Rows: {self.row_count}",
            f"- Updated rows: {self.updated_row_count}",
            f"- Worksheet preflight: `{self.preflight_status}`",
            f"- Preflight report: `{self.preflight_path}`",
            "",
            "## Updated Rows",
            "",
        ]
        if self.updated_rows:
            lines.append("| type | id | answer filled | evidence filled |")
            lines.append("| --- | --- | --- | --- |")
            for row in self.updated_rows:
                lines.append(
                    "| `{row_type}` | `{item_id}` | `{answer}` | `{evidence}` |".format(
                        row_type=row["row_type"],
                        item_id=row["field_or_question_id"],
                        answer=row["answer_filled"],
                        evidence=row["evidence_filled"],
                    )
                )
        else:
            lines.append("- No worksheet rows were updated from CLI inputs.")
        lines.extend(["", "## Missing Explicit Inputs"])
        if self.missing_inputs:
            lines.extend(f"- `{item}`" for item in self.missing_inputs)
        else:
            lines.append("- None.")
        lines.extend(["", "## Next Commands"])
        for command in self.next_commands:
            lines.extend(["", "```powershell", command, "```"])
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def fill_source_qa_evidence_worksheet(
    *,
    checklist_path: str | Path = "data_exports/data_source_qa.json",
    worksheet_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    encoding: str = "utf-8-sig",
    vendor: str | None = None,
    terminal: str | None = None,
    operator: str | None = None,
    exported_at: str | None = None,
    price_adjustment: str | None = None,
    license_scope: str | None = None,
    reviewed_by: str | None = None,
    reviewed_at: str | None = None,
    source_identity_evidence: str | None = None,
    license_evidence: str | None = None,
    price_adjustment_evidence: str | None = None,
    point_in_time_evidence: str | None = None,
    manual_signoff_evidence: str | None = None,
    vendor_evidence: str | None = None,
    terminal_evidence: str | None = None,
    operator_evidence: str | None = None,
    exported_at_evidence: str | None = None,
    price_adjustment_metadata_evidence: str | None = None,
    license_scope_evidence: str | None = None,
    reviewed_by_evidence: str | None = None,
    reviewed_at_evidence: str | None = None,
    notes: str | None = None,
) -> tuple[SourceQAWorksheetFillReport, SourceQAEvidenceWorksheetPreflightReport]:
    checklist_file = Path(checklist_path)
    worksheet_file = Path(worksheet_path) if worksheet_path else checklist_file.parent / "data_source_qa_evidence_worksheet.csv"
    root = Path(output_dir) if output_dir else worksheet_file.parent
    target_worksheet = root / worksheet_file.name

    base = build_data_source_qa_evidence_worksheet(checklist_path=checklist_file, output_dir=root)
    rows, source_rows = _load_rows(worksheet_file, base=base, encoding=encoding)
    updates = _row_updates(
        vendor=vendor,
        terminal=terminal,
        operator=operator,
        exported_at=exported_at,
        price_adjustment=price_adjustment,
        license_scope=license_scope,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        source_identity_evidence=source_identity_evidence,
        license_evidence=license_evidence,
        price_adjustment_evidence=price_adjustment_evidence,
        point_in_time_evidence=point_in_time_evidence,
        manual_signoff_evidence=manual_signoff_evidence,
        vendor_evidence=vendor_evidence,
        terminal_evidence=terminal_evidence,
        operator_evidence=operator_evidence,
        exported_at_evidence=exported_at_evidence,
        price_adjustment_metadata_evidence=price_adjustment_metadata_evidence,
        license_scope_evidence=license_scope_evidence,
        reviewed_by_evidence=reviewed_by_evidence,
        reviewed_at_evidence=reviewed_at_evidence,
        notes=notes,
    )
    updated_rows = _apply_updates(rows, updates)

    worksheet = SourceQAEvidenceWorksheet(
        checklist_path=str(checklist_file),
        rows=[_row_from_dict(row) for row in rows],
        workflow_commands=base.workflow_commands,
        safety_boundaries=base.safety_boundaries,
    )
    write_data_source_qa_evidence_worksheet(worksheet, root)
    if target_worksheet != root / "data_source_qa_evidence_worksheet.csv":
        _write_rows(target_worksheet, worksheet=worksheet, rows=rows, encoding=encoding)

    preflight = build_data_source_qa_evidence_worksheet_preflight(
        checklist_path=checklist_file,
        worksheet_path=target_worksheet,
        encoding=encoding,
    )
    write_data_source_qa_evidence_worksheet_preflight(preflight, root)
    report = _fill_report(
        checklist_file=checklist_file,
        worksheet_file=target_worksheet,
        output_dir=root,
        source_rows=source_rows,
        rows=rows,
        updated_rows=updated_rows,
        missing_inputs=_missing_required_inputs(
            vendor=vendor,
            terminal=terminal,
            operator=operator,
            exported_at=exported_at,
            price_adjustment=price_adjustment,
            license_scope=license_scope,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
            source_identity_evidence=source_identity_evidence,
            license_evidence=license_evidence,
            price_adjustment_evidence=price_adjustment_evidence,
            point_in_time_evidence=point_in_time_evidence,
            manual_signoff_evidence=manual_signoff_evidence,
        ),
        preflight=preflight,
    )
    write_source_qa_worksheet_fill_report(report, root)
    return report, preflight


def write_source_qa_worksheet_fill_report(
    report: SourceQAWorksheetFillReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "data_source_qa_worksheet_fill.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "data_source_qa_worksheet_fill.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _load_rows(
    worksheet_file: Path,
    *,
    base: SourceQAEvidenceWorksheet,
    encoding: str,
) -> tuple[list[dict[str, str]], str]:
    if worksheet_file.exists():
        return _read_rows(worksheet_file, encoding=encoding), "existing_worksheet"
    return [row.to_dict() for row in base.rows], "generated_from_checklist"


def _read_rows(path: Path, *, encoding: str) -> list[dict[str, str]]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        return [_canonical_row(row) for row in rows if isinstance(row, dict)]
    with path.open("r", newline="", encoding=encoding) as handle:
        return [_canonical_row(row) for row in csv.DictReader(handle)]


def _write_rows(
    path: Path,
    *,
    worksheet: SourceQAEvidenceWorksheet,
    rows: list[dict[str, str]],
    encoding: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        path.write_text(
            json.dumps(worksheet.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return
    with path.open("w", newline="", encoding=encoding) as handle:
        writer = csv.DictWriter(handle, fieldnames=WORKSHEET_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def _canonical_row(row: dict[str, Any]) -> dict[str, str]:
    return {field: str(row.get(field, "") or "") for field in WORKSHEET_FIELDNAMES}


def _row_from_dict(row: dict[str, str]) -> SourceQAEvidenceWorksheetRow:
    canonical = _canonical_row(row)
    return SourceQAEvidenceWorksheetRow(
        row_type=canonical["row_type"],
        field_or_question_id=canonical["field_or_question_id"],
        cli_argument=canonical["cli_argument"],
        severity=canonical["severity"],
        question_or_field=canonical["question_or_field"],
        required_evidence=canonical["required_evidence"],
        why_it_matters=canonical["why_it_matters"],
        answer=canonical["answer"],
        evidence=canonical["evidence"],
        notes=canonical["notes"],
    )


def _row_updates(
    *,
    vendor: str | None,
    terminal: str | None,
    operator: str | None,
    exported_at: str | None,
    price_adjustment: str | None,
    license_scope: str | None,
    reviewed_by: str | None,
    reviewed_at: str | None,
    source_identity_evidence: str | None,
    license_evidence: str | None,
    price_adjustment_evidence: str | None,
    point_in_time_evidence: str | None,
    manual_signoff_evidence: str | None,
    vendor_evidence: str | None,
    terminal_evidence: str | None,
    operator_evidence: str | None,
    exported_at_evidence: str | None,
    price_adjustment_metadata_evidence: str | None,
    license_scope_evidence: str | None,
    reviewed_by_evidence: str | None,
    reviewed_at_evidence: str | None,
    notes: str | None,
) -> dict[tuple[str, str], dict[str, str]]:
    default_note = _clean(notes)
    return {
        ("metadata", "data_vendor_or_broker"): _update(
            answer=vendor,
            evidence=vendor_evidence or source_identity_evidence,
            notes=default_note,
        ),
        ("metadata", "terminal_or_product_name"): _update(
            answer=terminal,
            evidence=terminal_evidence or source_identity_evidence,
            notes=default_note,
        ),
        ("metadata", "export_operator"): _update(
            answer=operator,
            evidence=operator_evidence or source_identity_evidence,
            notes=default_note,
        ),
        ("metadata", "exported_at_local_time"): _update(
            answer=exported_at,
            evidence=exported_at_evidence or source_identity_evidence,
            notes=default_note,
        ),
        ("metadata", "price_adjustment"): _update(
            answer=price_adjustment,
            evidence=price_adjustment_metadata_evidence or price_adjustment_evidence,
            notes=default_note,
        ),
        ("metadata", "license_or_usage_scope"): _update(
            answer=license_scope,
            evidence=license_scope_evidence or license_evidence,
            notes=default_note,
        ),
        ("metadata", "reviewed_by"): _update(
            answer=reviewed_by,
            evidence=reviewed_by_evidence or manual_signoff_evidence,
            notes=default_note,
        ),
        ("metadata", "reviewed_at"): _update(
            answer=reviewed_at,
            evidence=reviewed_at_evidence or manual_signoff_evidence,
            notes=default_note,
        ),
        ("source_question", "source_identity"): _update(
            answer="yes" if _evidence_can_answer_yes(source_identity_evidence) else "",
            evidence=source_identity_evidence,
            notes=default_note,
        ),
        ("source_question", "license_scope"): _update(
            answer="yes" if _evidence_can_answer_yes(license_evidence) else "",
            evidence=license_evidence,
            notes=default_note,
        ),
        ("source_question", "price_adjustment"): _update(
            answer="yes" if _evidence_can_answer_yes(price_adjustment_evidence) else "",
            evidence=price_adjustment_evidence,
            notes=default_note,
        ),
        ("source_question", "point_in_time"): _update(
            answer="yes" if _evidence_can_answer_yes(point_in_time_evidence) else "",
            evidence=point_in_time_evidence,
            notes=default_note,
        ),
        ("source_question", "manual_signoff"): _update(
            answer="yes" if _evidence_can_answer_yes(manual_signoff_evidence) else "",
            evidence=manual_signoff_evidence,
            notes=default_note,
        ),
    }


def _update(
    *,
    answer: str | None = None,
    evidence: str | None = None,
    notes: str | None = None,
) -> dict[str, str]:
    return {
        key: value
        for key, value in {
            "answer": _clean(answer),
            "evidence": _clean(evidence),
            "notes": _clean(notes),
        }.items()
        if value
    }


def _evidence_can_answer_yes(value: str | None) -> bool:
    text = _clean(value)
    return bool(text) and not weak_source_evidence(text) and not _references_generated_artifact(text)


def _references_generated_artifact(text: str) -> bool:
    lowered = text.lower()
    blocked_tokens = {
        "data_source_qa_evidence_worksheet",
        "source_qa_evidence_attachment_plan",
        "source_qa_evidence_manifest",
        "data_source_qa_answers_template",
        "first_million_evidence_work_order",
        "evidence_intake_kit",
        "operator_handoff",
    }
    if any(token in lowered for token in blocked_tokens):
        return True
    path_tokens = {
        "example",
        "examples",
        "fake",
        "generated",
        "mock",
        "placeholder",
        "plan",
        "readme",
        "sample",
        "template",
        "todo",
        "worksheet",
    }
    candidates = re.findall(r"[A-Za-z0-9_. -]*[\\/][A-Za-z0-9_.\\/ -]+|[A-Za-z0-9_.-]+\.[A-Za-z0-9]+", text)
    for candidate in candidates:
        tokens = set(re.findall(r"[a-z0-9]+", candidate.lower()))
        if tokens & path_tokens:
            return True
    return False


def _apply_updates(
    rows: list[dict[str, str]],
    updates: dict[tuple[str, str], dict[str, str]],
) -> list[dict[str, str]]:
    updated: list[dict[str, str]] = []
    for row in rows:
        key = (
            str(row.get("row_type", "")).strip(),
            str(row.get("field_or_question_id", "")).strip(),
        )
        patch = updates.get(key, {})
        if not patch:
            continue
        before_answer = str(row.get("answer", "") or "")
        before_evidence = str(row.get("evidence", "") or "")
        for field, value in patch.items():
            row[field] = value
        updated.append(
            {
                "row_type": key[0],
                "field_or_question_id": key[1],
                "answer_filled": "yes" if str(row.get("answer", "") or "") != before_answer else "no",
                "evidence_filled": "yes" if str(row.get("evidence", "") or "") != before_evidence else "no",
            }
        )
    return updated


def _missing_required_inputs(**values: str | None) -> list[str]:
    missing: list[str] = []
    for key, arg_name in REQUIRED_FILL_INPUTS.items():
        if not _clean(values.get(key)):
            missing.append(arg_name)
    return missing


def _fill_report(
    *,
    checklist_file: Path,
    worksheet_file: Path,
    output_dir: Path,
    source_rows: str,
    rows: list[dict[str, str]],
    updated_rows: list[dict[str, str]],
    missing_inputs: list[str],
    preflight: SourceQAEvidenceWorksheetPreflightReport,
) -> SourceQAWorksheetFillReport:
    status = "BLOCK" if missing_inputs or preflight.status == "BLOCK" else preflight.status
    return SourceQAWorksheetFillReport(
        status=status,
        checklist_path=str(checklist_file),
        worksheet_path=str(worksheet_file),
        output_dir=str(output_dir),
        source_rows=source_rows,
        row_count=len(rows),
        updated_row_count=len(updated_rows),
        updated_rows=updated_rows,
        missing_inputs=missing_inputs,
        preflight_status=preflight.status,
        preflight_path=str(output_dir / "data_source_qa_worksheet_preflight.json"),
        next_commands=_next_commands(
            checklist_file=checklist_file,
            worksheet_file=worksheet_file,
            output_dir=output_dir,
            status=status,
        ),
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def _next_commands(
    *,
    checklist_file: Path,
    worksheet_file: Path,
    output_dir: Path,
    status: str,
) -> list[str]:
    if status == "BLOCK":
        return [
            (
                ".\\.venv\\Scripts\\python.exe examples\\fill_data_source_qa_evidence_worksheet.py "
                f"--checklist {checklist_file} --worksheet {worksheet_file} "
                "--vendor \"...\" --terminal \"...\" --operator \"...\" --exported-at \"...\" "
                "--price-adjustment \"...\" --license-scope \"...\" --reviewed-by \"...\" "
                "--reviewed-at \"...\" --source-identity-evidence \"...\" "
                "--license-evidence \"...\" --price-adjustment-evidence \"...\" "
                "--point-in-time-evidence \"...\" --manual-signoff-evidence \"...\""
            )
        ]
    return [
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
            f"--checklist {checklist_file} "
            f"--evidence-dir {output_dir / 'source_qa_evidence'} --output-dir {output_dir} --strict"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_answers.py "
            f"--checklist {checklist_file} --worksheet {worksheet_file} "
            f"--output {output_dir / 'data_source_qa_answers.json'} "
            f"--evidence-manifest {output_dir / 'source_qa_evidence_manifest.json'} "
            "--require-evidence-manifest"
        ),
    ]


def _clean(value: str | None) -> str:
    return str(value or "").strip()
