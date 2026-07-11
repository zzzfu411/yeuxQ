"""Source-level QA checklist for offline A-share data exports."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from quantify.data.csv_contract import RESEARCH_CSV_SCHEMAS
from quantify.utils.config import load_config

QASeverity = Literal["BLOCK_IF_NO", "WATCH_IF_NO", "INFO"]
QAReviewStage = Literal["source", "csv_validation"]
QAStatus = Literal["PASS", "WATCH", "BLOCK"]
WorksheetRowType = Literal["metadata", "source_question"]

REQUIRED_SOURCE_METADATA = [
    "data_vendor_or_broker",
    "terminal_or_product_name",
    "export_operator",
    "exported_at_local_time",
    "price_adjustment",
    "license_or_usage_scope",
    "reviewed_by",
    "reviewed_at",
]

_ANGLE_PLACEHOLDER_RE = re.compile(r"<[^<>]+>")
_PLACEHOLDER_PREFIXES = ("todo", "tbd", "fixme", "changeme")
_PLACEHOLDER_VALUES = {
    "-",
    "--",
    "date",
    "evidence",
    "evidence-or-non-pit-note",
    "fill in",
    "fill me",
    "missing",
    "n.a.",
    "n/a",
    "na",
    "name",
    "none",
    "not applicable",
    "not provided",
    "not supplied",
    "operator",
    "placeholder",
    "terminal-name",
    "to be filled",
    "unknown",
    "unspecified",
    "vendor-or-broker",
    "local-time",
}
_PLACEHOLDER_ATTACHMENT_SUFFIXES = {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".log"}
_ATTACHMENT_TEXT_SAMPLE_BYTES = 8192
_GENERATED_ATTACHMENT_FILE_NAMES = {
    "data-source-qa",
    "data-source-qa-answers-template",
    "data-source-qa-evidence-worksheet",
    "operator-handoff",
    "source-qa-evidence-attachment-plan",
    "source-qa-evidence-manifest",
    "source-qa-preflight",
}
_FORBIDDEN_ATTACHMENT_PATH_TOKENS = {
    "example",
    "examples",
    "fake",
    "generated",
    "mock",
    "placeholder",
    "placeholders",
    "plan",
    "plans",
    "readme",
    "sample",
    "samples",
    "template",
    "templates",
    "todo",
    "todos",
    "worksheet",
    "worksheets",
}


@dataclass(frozen=True, slots=True)
class DataSourceQAItem:
    id: str
    category: str
    review_stage: QAReviewStage
    severity: QASeverity
    question: str
    required_evidence: str
    why_it_matters: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "category": self.category,
            "review_stage": self.review_stage,
            "severity": self.severity,
            "question": self.question,
            "required_evidence": self.required_evidence,
            "why_it_matters": self.why_it_matters,
        }


@dataclass(frozen=True, slots=True)
class DataSourceQAChecklist:
    market: str
    frequency: str
    start: str
    end: str
    as_of: str
    min_symbols: int
    price_adjustment: str
    universe: dict[str, Any]
    expected_files: list[dict[str, Any]]
    source_metadata_template: dict[str, str]
    checklist: list[DataSourceQAItem]
    workflow_commands: list[str]
    safety_boundaries: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "frequency": self.frequency,
            "start": self.start,
            "end": self.end,
            "as_of": self.as_of,
            "min_symbols": self.min_symbols,
            "price_adjustment": self.price_adjustment,
            "universe": self.universe,
            "expected_files": self.expected_files,
            "source_metadata_template": self.source_metadata_template,
            "checklist": [item.to_dict() for item in self.checklist],
            "workflow_commands": self.workflow_commands,
            "safety_boundaries": self.safety_boundaries,
        }

    def to_markdown(self) -> str:
        lines = [
            "# A-share Data Source QA Checklist",
            "",
            "Use this before replacing the offline CSV templates with real vendor exports.",
            "It is a source-quality and reproducibility checklist, not a trading signal.",
            "",
            "## Scope",
            "",
            f"- Market: `{self.market}`",
            f"- Frequency: `{self.frequency}`",
            f"- Date range: `{self.start}` to `{self.end}`",
            f"- As-of: `{self.as_of or 'not supplied'}`",
            f"- Minimum symbols: {self.min_symbols}",
            f"- Price adjustment: `{self.price_adjustment}`",
            f"- Universe mode: `{self.universe['mode']}`",
            f"- Index context: `{self.universe['index_code']}`",
            f"- Include ST in investable universe: `{self.universe['include_st']}`",
            f"- Minimum history days: {self.universe['min_history_days']}",
            "",
            "## Source Metadata To Fill",
            "",
            "| field | value |",
            "| --- | --- |",
        ]
        for key, value in self.source_metadata_template.items():
            lines.append(f"| `{key}` | `{value}` |")
        lines.extend(
            [
                "",
                "## Expected Files",
                "",
                "| file | required | columns |",
                "| --- | --- | --- |",
            ]
        )
        for item in self.expected_files:
            required = "yes" if item["required"] else "recommended"
            columns = ", ".join(item["columns"])
            lines.append(f"| `{item['file_name']}` | `{required}` | `{columns}` |")
        lines.extend(
            [
                "",
                "## QA Questions",
                "",
                "| id | stage | severity | question | required evidence | why it matters |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for item in self.checklist:
            lines.append(
                f"| `{item.id}` | `{item.review_stage}` | `{item.severity}` | {item.question} | "
                f"{item.required_evidence} | {item.why_it_matters} |"
            )
        lines.extend(["", "## Workflow Commands"])
        for command in self.workflow_commands:
            lines.append("")
            lines.append("```powershell")
            lines.append(command)
            lines.append("```")
        lines.extend(["", "## Safety Boundaries"])
        lines.extend(f"- {item}" for item in self.safety_boundaries)
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class SourceQAEvidenceWorksheetRow:
    row_type: WorksheetRowType
    field_or_question_id: str
    cli_argument: str
    severity: str
    question_or_field: str
    required_evidence: str
    why_it_matters: str
    answer: str = ""
    evidence: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "row_type": self.row_type,
            "field_or_question_id": self.field_or_question_id,
            "cli_argument": self.cli_argument,
            "severity": self.severity,
            "question_or_field": self.question_or_field,
            "required_evidence": self.required_evidence,
            "why_it_matters": self.why_it_matters,
            "answer": self.answer,
            "evidence": self.evidence,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class SourceQAEvidenceWorksheet:
    checklist_path: str
    rows: list[SourceQAEvidenceWorksheetRow]
    workflow_commands: list[str]
    safety_boundaries: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "checklist_path": self.checklist_path,
            "rows": [row.to_dict() for row in self.rows],
            "workflow_commands": self.workflow_commands,
            "safety_boundaries": self.safety_boundaries,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Data Source QA Evidence Worksheet",
            "",
            "Fill this worksheet from real vendor, terminal, export, license, and human review evidence.",
            "It is a collection aid only; it does not create `data_source_qa_answers.json` or weaken gates.",
            "",
            f"- Checklist: `{self.checklist_path}`",
            "",
            "## Rows To Fill",
            "",
            "| type | id | CLI argument | severity | question or field | required evidence |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for row in self.rows:
            lines.append(
                f"| `{row.row_type}` | `{row.field_or_question_id}` | `{row.cli_argument}` | "
                f"`{row.severity}` | {row.question_or_field} | {row.required_evidence} |"
            )
        lines.extend(["", "## Workflow Commands"])
        for command in self.workflow_commands:
            lines.append("")
            lines.append("```powershell")
            lines.append(command)
            lines.append("```")
        lines.extend(["", "## Safety Boundaries"])
        lines.extend(f"- {item}" for item in self.safety_boundaries)
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class SourceQAEvidenceWorksheetPreflightFinding:
    status: QAStatus
    code: str
    row_number: int
    row_type: str
    field_or_question_id: str
    severity: str
    message: str
    fix: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "code": self.code,
            "row_number": self.row_number,
            "row_type": self.row_type,
            "field_or_question_id": self.field_or_question_id,
            "severity": self.severity,
            "message": self.message,
            "fix": self.fix,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class SourceQAEvidenceWorksheetPreflightReport:
    status: QAStatus
    checklist_path: str
    worksheet_path: str
    row_count: int
    findings: list[SourceQAEvidenceWorksheetPreflightFinding]
    next_commands: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checklist_path": self.checklist_path,
            "worksheet_path": self.worksheet_path,
            "row_count": self.row_count,
            "findings": [finding.to_dict() for finding in self.findings],
            "next_commands": self.next_commands,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Data Source QA Worksheet Preflight: {self.status}",
            "",
            f"- Checklist: `{self.checklist_path}`",
            f"- Worksheet: `{self.worksheet_path}`",
            f"- Rows: {self.row_count}",
            "",
            "## Findings",
            "",
        ]
        if self.findings:
            lines.append("| status | code | row | type | id | message | fix |")
            lines.append("| --- | --- | ---: | --- | --- | --- | --- |")
            for finding in self.findings:
                row_number = finding.row_number if finding.row_number else ""
                lines.append(
                    f"| `{finding.status}` | `{finding.code}` | {row_number} | "
                    f"`{finding.row_type}` | `{finding.field_or_question_id}` | "
                    f"{finding.message} | {finding.fix} |"
                )
        else:
            lines.append("- No worksheet issues found.")
        lines.extend(["", "## Next Commands"])
        for command in self.next_commands:
            lines.append("")
            lines.append("```powershell")
            lines.append(command)
            lines.append("```")
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class SourceQAEvidenceManifestItem:
    id: str
    path: str
    sha256: str
    size_bytes: int
    modified_at_utc: str
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "modified_at_utc": self.modified_at_utc,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class SourceQAEvidenceManifest:
    checklist_path: str
    evidence_dir: str
    items: list[SourceQAEvidenceManifestItem]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_type": "source_qa_evidence_manifest",
            "checklist_path": self.checklist_path,
            "evidence_dir": self.evidence_dir,
            "items": [item.to_dict() for item in self.items],
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Source QA Evidence Manifest",
            "",
            f"- Checklist: `{self.checklist_path}`",
            f"- Evidence directory: `{self.evidence_dir}`",
            "",
            "This manifest records local evidence attachments and file hashes. It is not a source QA PASS by itself.",
            "",
            "## Attachments",
            "",
            "| id | path | sha256 | size | modified utc | notes |",
            "| --- | --- | --- | ---: | --- | --- |",
        ]
        for item in self.items:
            lines.append(
                f"| `{item.id}` | `{item.path}` | `{item.sha256}` | "
                f"{item.size_bytes} | `{item.modified_at_utc}` | {item.notes} |"
            )
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class SourceQAEvidenceManifestPreflightFinding:
    status: QAStatus
    code: str
    item_id: str
    message: str
    fix: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "code": self.code,
            "item_id": self.item_id,
            "message": self.message,
            "fix": self.fix,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class SourceQAEvidenceManifestPreflightReport:
    status: QAStatus
    checklist_path: str
    manifest_path: str
    evidence_dir: str
    required_attachment_ids: list[str]
    valid_required_ids: list[str]
    missing_required_ids: list[str]
    invalid_attachment_count: int
    findings: list[SourceQAEvidenceManifestPreflightFinding]
    next_commands: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checklist_path": self.checklist_path,
            "manifest_path": self.manifest_path,
            "evidence_dir": self.evidence_dir,
            "required_attachment_ids": self.required_attachment_ids,
            "valid_required_ids": self.valid_required_ids,
            "missing_required_ids": self.missing_required_ids,
            "invalid_attachment_count": self.invalid_attachment_count,
            "findings": [finding.to_dict() for finding in self.findings],
            "next_commands": self.next_commands,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Source QA Evidence Manifest Preflight: {self.status}",
            "",
            f"- Checklist: `{self.checklist_path}`",
            f"- Manifest: `{self.manifest_path}`",
            f"- Evidence directory: `{self.evidence_dir}`",
            f"- Required attachments: {len(self.required_attachment_ids)}",
            f"- Valid required attachments: {len(self.valid_required_ids)}",
            f"- Missing required attachments: {len(self.missing_required_ids)}",
            f"- Invalid attachments: {self.invalid_attachment_count}",
            "",
            "## Findings",
            "",
        ]
        if self.findings:
            lines.append("| status | code | id | message | fix |")
            lines.append("| --- | --- | --- | --- | --- |")
            for finding in self.findings:
                lines.append(
                    f"| `{finding.status}` | `{finding.code}` | `{finding.item_id}` | "
                    f"{finding.message} | {finding.fix} |"
                )
        else:
            lines.append("- No manifest coverage issues found.")
        lines.extend(["", "## Next Commands"])
        for command in self.next_commands:
            lines.append("")
            lines.append("```powershell")
            lines.append(command)
            lines.append("```")
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class DataSourceQAReviewFinding:
    severity: QAStatus
    code: str
    message: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class DataSourceQAReview:
    status: QAStatus
    review_stage: QAReviewStage
    checklist_path: str
    answers_path: str
    validation_report_path: str
    evidence_manifest_path: str
    require_evidence_manifest: bool
    source_metadata: dict[str, Any]
    missing_metadata: list[str]
    findings: list[DataSourceQAReviewFinding]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "review_stage": self.review_stage,
            "checklist_path": self.checklist_path,
            "answers_path": self.answers_path,
            "validation_report_path": self.validation_report_path,
            "evidence_manifest_path": self.evidence_manifest_path,
            "require_evidence_manifest": self.require_evidence_manifest,
            "source_metadata": self.source_metadata,
            "missing_metadata": self.missing_metadata,
            "findings": [finding.to_dict() for finding in self.findings],
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Data Source QA Review: {self.status}",
            "",
            f"- Review stage: `{self.review_stage}`",
            f"- Checklist: `{self.checklist_path}`",
            f"- Answers: `{self.answers_path}`",
            f"- CSV validation report: `{self.validation_report_path or 'not supplied'}`",
            f"- Evidence manifest: `{self.evidence_manifest_path or 'not supplied'}`",
            f"- Require evidence manifest: `{self.require_evidence_manifest}`",
            "",
            "## Source Metadata",
            "",
            "| field | value |",
            "| --- | --- |",
        ]
        for key, value in self.source_metadata.items():
            lines.append(f"| `{key}` | `{value}` |")
        lines.extend(["", "## Missing Metadata"])
        if self.missing_metadata:
            lines.extend(f"- `{item}`" for item in self.missing_metadata)
        else:
            lines.append("- None.")
        lines.extend(["", "## Findings"])
        if self.findings:
            for finding in self.findings:
                evidence = ", ".join(f"{key}={value}" for key, value in finding.evidence.items())
                lines.append(
                    f"- `{finding.severity}` `{finding.code}`: {finding.message}"
                    f" ({evidence or 'n/a'})"
                )
        else:
            lines.append("- No findings.")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_data_source_qa(
    *,
    config_path: str | Path | None = None,
    output_dir: str | Path = "data_exports",
    start: str | None = None,
    end: str | None = None,
    min_symbols: int = 300,
    as_of: str | None = None,
) -> DataSourceQAChecklist:
    cfg = _load_config(config_path)
    research = cfg.get("research", {})
    data = cfg.get("data", {})
    universe_cfg = cfg.get("universe", {})
    resolved_start = start or str(research.get("start", ""))
    resolved_end = end or str(research.get("end", ""))
    price_adjustment = str(data.get("adjust", "qfq"))
    universe = {
        "mode": str(universe_cfg.get("mode", "all_a")),
        "index_code": str(universe_cfg.get("index_code", "")),
        "include_st": bool(universe_cfg.get("include_st", False)),
        "min_history_days": int(universe_cfg.get("min_history_days", 0) or 0),
    }
    data_dir = Path(output_dir)
    return DataSourceQAChecklist(
        market="A-share equities",
        frequency="daily",
        start=resolved_start,
        end=resolved_end,
        as_of=as_of or "",
        min_symbols=min_symbols,
        price_adjustment=price_adjustment,
        universe=universe,
        expected_files=[
            {
                "role": schema.role,
                "file_name": schema.file_name,
                "path": str(data_dir / schema.file_name),
                "required": schema.required,
                "columns": schema.columns,
                "description": schema.description,
            }
            for schema in RESEARCH_CSV_SCHEMAS
        ],
        source_metadata_template=_source_metadata_template(price_adjustment, resolved_start, resolved_end),
        checklist=_qa_items(price_adjustment),
        workflow_commands=_workflow_commands(
            data_dir=data_dir,
            config_path=str(config_path or "config\\research_recent.yaml"),
            min_symbols=min_symbols,
            as_of=as_of,
        ),
        safety_boundaries=[
            "This QA checklist is for data sourcing, research, and paper trading only.",
            "Do not use a source checklist as evidence that a strategy is profitable.",
            "Do not continue while any BLOCK_IF_NO source question is unanswered or negative.",
            "Do not connect these CSV exports to real broker order submission.",
            "After CSV import, real_data_bootstrap, data_audit, robustness, and paper gates still decide readiness.",
        ],
    )


def write_data_source_qa(checklist: DataSourceQAChecklist, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    checklist_path = root / "data_source_qa.json"
    (root / "data_source_qa.json").write_text(
        json.dumps(checklist.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "data_source_qa.md").write_text(checklist.to_markdown(), encoding="utf-8")
    (root / "data_source_qa_answers_template.json").write_text(
        json.dumps(_answers_template(checklist), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_data_source_qa_evidence_worksheet(
        _evidence_worksheet_from_checklist(
            checklist.to_dict(),
            checklist_path=checklist_path,
            output_dir=root,
        ),
        root,
    )
    return root


def build_data_source_qa_evidence_worksheet(
    *,
    checklist_path: str | Path = "data_exports/data_source_qa.json",
    output_dir: str | Path | None = None,
) -> SourceQAEvidenceWorksheet:
    checklist_file = Path(checklist_path)
    root = Path(output_dir) if output_dir is not None else checklist_file.parent
    return _evidence_worksheet_from_checklist(
        _read_json(checklist_file),
        checklist_path=checklist_file,
        output_dir=root,
    )


def write_data_source_qa_evidence_worksheet(
    worksheet: SourceQAEvidenceWorksheet,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "data_source_qa_evidence_worksheet.json").write_text(
        json.dumps(worksheet.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "data_source_qa_evidence_worksheet.md").write_text(
        worksheet.to_markdown(),
        encoding="utf-8",
    )
    csv_path = root / "data_source_qa_evidence_worksheet.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=_worksheet_fieldnames())
        writer.writeheader()
        for row in worksheet.rows:
            writer.writerow(row.to_dict())
    return root


def build_data_source_qa_answers(
    *,
    checklist_path: str | Path = "data_exports/data_source_qa.json",
    data_vendor_or_broker: str,
    terminal_or_product_name: str,
    export_operator: str,
    exported_at_local_time: str,
    price_adjustment: str,
    price_adjustment_evidence: str,
    license_or_usage_scope: str,
    license_evidence: str,
    point_in_time_evidence: str,
    reviewed_by: str,
    reviewed_at: str,
    encoding: str = "utf-8-sig",
    known_limitations: str = "",
) -> dict[str, Any]:
    checklist = _read_json(Path(checklist_path))
    template = checklist.get("source_metadata_template", {}) or {}
    source_metadata = {
        **template,
        "data_vendor_or_broker": data_vendor_or_broker,
        "terminal_or_product_name": terminal_or_product_name,
        "export_operator": export_operator,
        "exported_at_local_time": exported_at_local_time,
        "price_adjustment": price_adjustment,
        "encoding": encoding,
        "license_or_usage_scope": license_or_usage_scope,
        "known_limitations": known_limitations,
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at,
    }
    answers: dict[str, dict[str, str]] = {}
    for item in checklist.get("checklist", []) or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", ""))
        review_stage = str(item.get("review_stage", "source"))
        answers[item_id] = {
            "answer": "",
            "evidence": "",
            "review_stage": review_stage,
            "notes": "",
        }
    source_evidence = (
        f"vendor={data_vendor_or_broker}; terminal={terminal_or_product_name}; "
        f"operator={export_operator}; exported_at={exported_at_local_time}"
    )
    _set_answer(answers, "source_identity", source_evidence)
    _set_answer(answers, "license_scope", license_evidence)
    _set_answer(answers, "price_adjustment", price_adjustment_evidence)
    _set_answer(answers, "point_in_time", point_in_time_evidence)
    _set_answer(answers, "manual_signoff", f"reviewed_by={reviewed_by}; reviewed_at={reviewed_at}")
    return {"source_metadata": source_metadata, "answers": answers}


def build_data_source_qa_answers_from_evidence_worksheet(
    *,
    checklist_path: str | Path = "data_exports/data_source_qa.json",
    worksheet_path: str | Path = "data_exports/data_source_qa_evidence_worksheet.csv",
    encoding: str = "utf-8-sig",
    worksheet_text: str | None = None,
) -> dict[str, Any]:
    checklist = _read_json(Path(checklist_path))
    rows = _read_worksheet_rows(Path(worksheet_path), encoding=encoding, worksheet_text=worksheet_text)
    template = checklist.get("source_metadata_template", {}) or {}
    source_metadata = {**template}
    answers: dict[str, dict[str, str]] = {}
    for item in checklist.get("checklist", []) or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", ""))
        answers[item_id] = {
            "answer": "",
            "evidence": "",
            "review_stage": str(item.get("review_stage", "source")),
            "notes": "",
        }
    for row in rows:
        row_type = str(row.get("row_type", "")).strip()
        field_or_question_id = str(row.get("field_or_question_id", "")).strip()
        answer = str(row.get("answer", "")).strip()
        evidence = str(row.get("evidence", "")).strip()
        notes = str(row.get("notes", "")).strip()
        if row_type == "metadata" and field_or_question_id:
            if answer:
                source_metadata[field_or_question_id] = answer
            if field_or_question_id == "license_or_usage_scope" and evidence:
                _set_or_create_answer(answers, "license_scope", "yes", evidence, notes=notes)
            continue
        if row_type != "source_question" or not field_or_question_id:
            continue
        if field_or_question_id not in answers:
            continue
        resolved_answer = _worksheet_answer(answer, evidence)
        answers[field_or_question_id]["answer"] = resolved_answer
        answers[field_or_question_id]["evidence"] = evidence
        answers[field_or_question_id]["notes"] = notes
    _fill_derived_source_answers_from_metadata(source_metadata, answers)
    return {"source_metadata": source_metadata, "answers": answers}


def build_data_source_qa_evidence_worksheet_preflight(
    *,
    checklist_path: str | Path = "data_exports/data_source_qa.json",
    worksheet_path: str | Path = "data_exports/data_source_qa_evidence_worksheet.csv",
    encoding: str = "utf-8-sig",
    worksheet_text: str | None = None,
) -> SourceQAEvidenceWorksheetPreflightReport:
    checklist_file = Path(checklist_path)
    worksheet_file = Path(worksheet_path)
    checklist = _read_json(checklist_file)
    rows = _read_worksheet_rows(worksheet_file, encoding=encoding, worksheet_text=worksheet_text)
    findings: list[SourceQAEvidenceWorksheetPreflightFinding] = []
    if not checklist_file.exists():
        findings.append(
            _worksheet_preflight_finding(
                "BLOCK",
                "SOURCE_QA_CHECKLIST_MISSING",
                row_number=0,
                row_type="artifact",
                field_or_question_id="data_source_qa.json",
                severity="BLOCK_IF_NO",
                message="Source QA checklist is missing.",
                fix="Generate data_source_qa.json before filling or preflighting the worksheet.",
                evidence={"target": str(checklist_file)},
            )
        )
    if worksheet_text is None and not worksheet_file.exists():
        findings.append(
            _worksheet_preflight_finding(
                "BLOCK",
                "SOURCE_QA_WORKSHEET_MISSING",
                row_number=0,
                row_type="artifact",
                field_or_question_id="data_source_qa_evidence_worksheet",
                severity="BLOCK_IF_NO",
                message="Source QA evidence worksheet is missing.",
                fix="Run write_data_source_qa_evidence_worksheet.py, fill it from real source evidence, then rerun this preflight.",
                evidence={"target": str(worksheet_file)},
            )
        )
    if not rows:
        findings.append(
            _worksheet_preflight_finding(
                "BLOCK",
                "SOURCE_QA_WORKSHEET_EMPTY",
                row_number=0,
                row_type="artifact",
                field_or_question_id="data_source_qa_evidence_worksheet",
                severity="BLOCK_IF_NO",
                message="Source QA evidence worksheet has no rows.",
                fix="Regenerate the worksheet from data_source_qa.json and fill the required rows.",
                evidence={"target": str(worksheet_file)},
            )
        )
    metadata_seen: set[str] = set()
    source_question_seen: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        row_type = str(row.get("row_type", "")).strip()
        item_id = str(row.get("field_or_question_id", "")).strip()
        severity = str(row.get("severity", "")).strip().upper()
        answer = str(row.get("answer", "")).strip()
        evidence = str(row.get("evidence", "")).strip()
        if not row_type or not item_id:
            findings.append(
                _worksheet_preflight_finding(
                    "BLOCK",
                    "SOURCE_QA_WORKSHEET_ROW_INVALID",
                    row_number=row_number,
                    row_type=row_type or "unknown",
                    field_or_question_id=item_id or "unknown",
                    severity=severity,
                    message="Worksheet row is missing row_type or field_or_question_id.",
                    fix="Regenerate the worksheet or restore the required CSV columns.",
                    evidence={"row": _worksheet_preflight_row_payload(row)},
                )
            )
            continue
        if row_type == "metadata":
            metadata_seen.add(item_id)
            findings.extend(
                _worksheet_metadata_preflight_findings(
                    row_number=row_number,
                    item_id=item_id,
                    severity=severity,
                    answer=answer,
                    evidence=evidence,
                    row=row,
                )
            )
            continue
        if row_type == "source_question":
            source_question_seen.add(item_id)
            findings.extend(
                _worksheet_source_question_preflight_findings(
                    row_number=row_number,
                    item_id=item_id,
                    severity=severity,
                    answer=answer,
                    evidence=evidence,
                    row=row,
                )
            )
            continue
        findings.append(
            _worksheet_preflight_finding(
                "BLOCK",
                "SOURCE_QA_WORKSHEET_ROW_TYPE_INVALID",
                row_number=row_number,
                row_type=row_type,
                field_or_question_id=item_id,
                severity=severity,
                message="Worksheet row_type must be metadata or source_question.",
                fix="Regenerate the worksheet from data_source_qa.json.",
                evidence={"row": _worksheet_preflight_row_payload(row)},
            )
        )
    for missing_field in [field for field in REQUIRED_SOURCE_METADATA if field not in metadata_seen]:
        findings.append(
            _worksheet_preflight_finding(
                "BLOCK",
                "SOURCE_QA_WORKSHEET_REQUIRED_METADATA_ROW_MISSING",
                row_number=0,
                row_type="metadata",
                field_or_question_id=missing_field,
                severity="REQUIRED",
                message="Required metadata row is missing from the worksheet.",
                fix="Regenerate the worksheet before writing data_source_qa_answers.json.",
                evidence={"target": str(worksheet_file)},
            )
        )
    for missing_item in _required_source_question_ids(checklist, source_question_seen):
        findings.append(
            _worksheet_preflight_finding(
                "BLOCK",
                "SOURCE_QA_WORKSHEET_REQUIRED_SOURCE_ROW_MISSING",
                row_number=0,
                row_type="source_question",
                field_or_question_id=missing_item,
                severity="BLOCK_IF_NO",
                message="Required source QA question row is missing from the worksheet.",
                fix="Regenerate the worksheet before writing data_source_qa_answers.json.",
                evidence={"target": str(worksheet_file), "id": missing_item},
            )
        )
    status = _review_status(
        [
            DataSourceQAReviewFinding(
                finding.status,
                finding.code,
                finding.message,
                finding.evidence,
            )
            for finding in findings
        ]
    )
    return SourceQAEvidenceWorksheetPreflightReport(
        status=status,
        checklist_path=str(checklist_file),
        worksheet_path=str(worksheet_file),
        row_count=len(rows),
        findings=findings,
        next_commands=_worksheet_preflight_next_commands(
            checklist_file=checklist_file,
            worksheet_file=worksheet_file,
            status=status,
        ),
        prohibited_actions=[
            "Do not generate data_source_qa_answers.json from a BLOCK worksheet preflight.",
            "Do not use placeholder, sample, or generated workflow files as source QA evidence.",
            "Do not invent vendor, license, adjustment, PIT, or reviewer evidence.",
            "Do not treat worksheet preflight PASS as strategy approval, profitability evidence, or live trading permission.",
            "Do not connect this workflow to real broker order submission.",
        ],
    )


def write_data_source_qa_evidence_worksheet_preflight(
    report: SourceQAEvidenceWorksheetPreflightReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "data_source_qa_worksheet_preflight.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "data_source_qa_worksheet_preflight.md").write_text(
        report.to_markdown(),
        encoding="utf-8",
    )
    return root


def write_data_source_qa_answers(answers: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(answers, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_source_qa_evidence_manifest(
    *,
    checklist_path: str | Path = "data_exports/data_source_qa.json",
    evidence_dir: str | Path = "data_exports/source_qa_evidence",
) -> SourceQAEvidenceManifest:
    checklist_file = Path(checklist_path)
    evidence_root = Path(evidence_dir)
    checklist = _read_json(checklist_file)
    source_ids = [
        str(item.get("id", "")).strip()
        for item in checklist.get("checklist", []) or []
        if isinstance(item, dict) and str(item.get("review_stage", "")) == "source"
    ]
    items: list[SourceQAEvidenceManifestItem] = []
    if evidence_root.exists():
        for path in sorted(item for item in evidence_root.rglob("*") if item.is_file()):
            evidence_id = _evidence_id_from_path(path, source_ids)
            if not evidence_id:
                continue
            stat = path.stat()
            items.append(
                SourceQAEvidenceManifestItem(
                    id=evidence_id,
                    path=str(path),
                    sha256=_file_sha256(path),
                    size_bytes=int(stat.st_size),
                    modified_at_utc=datetime.fromtimestamp(
                        stat.st_mtime,
                        tz=UTC,
                    ).isoformat(),
                )
            )
    return SourceQAEvidenceManifest(
        checklist_path=str(checklist_file),
        evidence_dir=str(evidence_root),
        items=items,
        prohibited_actions=[
            "Do not treat evidence attachment hashes as source QA approval by themselves.",
            "Do not attach screenshots or documents that you are not allowed to retain for research audit.",
            "Do not fabricate local files only to satisfy source QA evidence gates.",
            "Do not connect this manifest to real broker order submission.",
        ],
    )


def write_source_qa_evidence_manifest(
    manifest: SourceQAEvidenceManifest,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "source_qa_evidence_manifest.json").write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "source_qa_evidence_manifest.md").write_text(
        manifest.to_markdown(),
        encoding="utf-8",
    )
    return root


def build_source_qa_evidence_manifest_preflight(
    *,
    checklist_path: str | Path = "data_exports/data_source_qa.json",
    manifest_path: str | Path = "data_exports/source_qa_evidence_manifest.json",
    evidence_dir: str | Path | None = None,
) -> SourceQAEvidenceManifestPreflightReport:
    checklist_file = Path(checklist_path)
    manifest_file = Path(manifest_path)
    resolved_evidence_dir = Path(evidence_dir) if evidence_dir is not None else manifest_file.parent / "source_qa_evidence"
    checklist = _read_json(checklist_file)
    required_items = [
        item
        for item in checklist.get("checklist", []) or []
        if isinstance(item, dict)
        and str(item.get("review_stage", "")) == "source"
        and str(item.get("severity", "")).upper() == "BLOCK_IF_NO"
    ]
    required_by_id = {str(item.get("id", "")).strip(): item for item in required_items if str(item.get("id", "")).strip()}
    findings: list[SourceQAEvidenceManifestPreflightFinding] = []
    if not checklist_file.exists():
        findings.append(
            _manifest_preflight_finding(
                "BLOCK",
                "SOURCE_QA_CHECKLIST_MISSING",
                "data_source_qa",
                "Source QA checklist is missing.",
                "Generate data_source_qa.json before building the evidence manifest.",
                {"target": str(checklist_file)},
            )
        )
    manifest = _read_json(manifest_file)
    if not manifest_file.exists():
        findings.append(
            _manifest_preflight_finding(
                "BLOCK",
                "SOURCE_QA_EVIDENCE_MANIFEST_MISSING",
                "source_qa_evidence_manifest",
                "source_qa_evidence_manifest.json is missing.",
                "Add retained evidence files, run write_source_qa_evidence_manifest.py, then rerun this preflight.",
                {"target": str(manifest_file)},
            )
        )
        items: list[Any] = []
    else:
        raw_items = manifest.get("items", []) if isinstance(manifest, dict) else []
        if not isinstance(raw_items, list):
            findings.append(
                _manifest_preflight_finding(
                    "BLOCK",
                    "SOURCE_QA_EVIDENCE_MANIFEST_INVALID",
                    "source_qa_evidence_manifest",
                    "Evidence manifest items must be a list.",
                    "Regenerate source_qa_evidence_manifest.json from retained local evidence files.",
                    {"target": str(manifest_file)},
                )
            )
            items = []
        else:
            items = raw_items
    valid_required_ids: set[str] = set()
    invalid_attachment_count = 0
    seen_ids: set[str] = set()
    for raw_item in items:
        if not isinstance(raw_item, dict):
            invalid_attachment_count += 1
            findings.append(
                _manifest_preflight_finding(
                    "BLOCK",
                    "SOURCE_QA_EVIDENCE_MANIFEST_INVALID",
                    "source_qa_evidence_manifest",
                    "Evidence manifest contains a non-object item.",
                    "Regenerate source_qa_evidence_manifest.json.",
                    {"manifest_path": str(manifest_file)},
                )
            )
            continue
        item_id = str(raw_item.get("id", "")).strip()
        path_text = str(raw_item.get("path", "")).strip()
        sha256 = str(raw_item.get("sha256", "")).strip()
        if item_id:
            seen_ids.add(item_id)
        error = validate_source_qa_attachment(item_id=item_id, path_text=path_text, sha256=sha256)
        if error is not None:
            invalid_attachment_count += 1
            findings.append(
                _manifest_preflight_finding(
                    "BLOCK",
                    _manifest_preflight_error_code(str(error.get("code", "attachment_invalid"))),
                    item_id or "source_qa_attachment",
                    str(error.get("message", "Evidence attachment is invalid.")),
                    _manifest_preflight_fix(str(error.get("code", "attachment_invalid"))),
                    {
                        "manifest_path": str(manifest_file),
                        "id": item_id,
                        "path": path_text,
                        "sha256": sha256,
                        "error": error,
                    },
                )
            )
            continue
        if item_id in required_by_id:
            valid_required_ids.add(item_id)
    missing_ids = [item_id for item_id in required_by_id if item_id not in valid_required_ids]
    for item_id in missing_ids:
        item = required_by_id[item_id]
        findings.append(
            _manifest_preflight_finding(
                "BLOCK",
                "SOURCE_QA_EVIDENCE_ATTACHMENT_MISSING",
                item_id,
                "Required source QA evidence attachment is missing or invalid.",
                "Place a retained local evidence file under source_qa_evidence and regenerate the manifest.",
                {
                    "manifest_path": str(manifest_file),
                    "evidence_dir": str(resolved_evidence_dir),
                    "target": str(_source_qa_attachment_target(checklist_file, item_id)),
                    "question": str(item.get("question", "")),
                    "required_evidence": str(item.get("required_evidence", "")),
                    "seen_manifest_ids": sorted(seen_ids),
                },
            )
        )
    status = "BLOCK" if findings else "PASS"
    return SourceQAEvidenceManifestPreflightReport(
        status=status,
        checklist_path=str(checklist_file),
        manifest_path=str(manifest_file),
        evidence_dir=str(resolved_evidence_dir),
        required_attachment_ids=list(required_by_id),
        valid_required_ids=sorted(valid_required_ids),
        missing_required_ids=missing_ids,
        invalid_attachment_count=invalid_attachment_count,
        findings=findings,
        next_commands=_manifest_preflight_next_commands(
            checklist_file=checklist_file,
            manifest_file=manifest_file,
            evidence_dir=resolved_evidence_dir,
            status=status,
        ),
        prohibited_actions=[
            "Do not fabricate evidence files to satisfy manifest coverage.",
            "Do not use generated worksheet, plan, sample, placeholder, or README files as retained source evidence.",
            "Do not treat manifest preflight PASS as source QA approval by itself.",
            "Do not import offline data until strict source QA review passes.",
            "Do not connect this workflow to real broker order submission.",
        ],
    )


def write_source_qa_evidence_manifest_preflight(
    report: SourceQAEvidenceManifestPreflightReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "source_qa_evidence_manifest_preflight.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "source_qa_evidence_manifest_preflight.md").write_text(
        report.to_markdown(),
        encoding="utf-8",
    )
    return root


def build_data_source_qa_review(
    *,
    checklist_path: str | Path = "data_exports/data_source_qa.json",
    answers_path: str | Path = "data_exports/data_source_qa_answers.json",
    review_stage: QAReviewStage = "source",
    validation_report_path: str | Path | None = None,
    evidence_manifest_path: str | Path | None = None,
    require_evidence_manifest: bool = False,
) -> DataSourceQAReview:
    checklist_file = Path(checklist_path)
    answers_file = Path(answers_path)
    validation_file = Path(validation_report_path) if validation_report_path else None
    manifest_file = Path(evidence_manifest_path) if evidence_manifest_path else None
    findings: list[DataSourceQAReviewFinding] = []
    if not checklist_file.exists():
        findings.append(
            DataSourceQAReviewFinding(
                "BLOCK",
                "SOURCE_QA_CHECKLIST_MISSING",
                "data_source_qa.json is required before source QA can be reviewed.",
                {
                    "checklist_path": str(checklist_file),
                    "target": str(checklist_file),
                    "next_command": "Run write_data_source_qa.py to generate data_source_qa.json.",
                },
            )
        )
        return _review(
            checklist_path=checklist_file,
            answers_path=answers_file,
            validation_report_path=validation_file,
            evidence_manifest_path=manifest_file,
            require_evidence_manifest=require_evidence_manifest,
            review_stage=review_stage,
            source_metadata={},
            missing_metadata=[],
            findings=findings,
        )

    checklist = _read_json(checklist_file)
    answers = _read_json(answers_file) if answers_file.exists() else {}
    validation = _read_json(validation_file) if validation_file is not None and validation_file.exists() else {}
    manifest = _read_json(manifest_file) if manifest_file is not None and manifest_file.exists() else {}
    if not answers and review_stage == "source":
        findings.append(
            DataSourceQAReviewFinding(
                "BLOCK",
                "SOURCE_QA_ANSWERS_MISSING",
                "data_source_qa_answers.json is missing or empty; fill it before offline import.",
                {
                    "answers_path": str(answers_file),
                    "target": str(_source_qa_worksheet_path(checklist_file)),
                    "required_evidence": "Filled source metadata and source QA answers from real vendor/export evidence.",
                },
            )
        )
    source_metadata = _metadata(answers)
    missing_metadata = _missing_required_metadata(source_metadata) if review_stage == "source" else []
    if missing_metadata and review_stage == "source":
        findings.append(
            DataSourceQAReviewFinding(
                "BLOCK",
                "SOURCE_METADATA_MISSING",
                "Required source metadata fields are missing.",
                {
                    "missing_metadata": missing_metadata,
                    "target": str(_source_qa_worksheet_path(checklist_file)),
                    "required_evidence": "Fill all required source_metadata fields from real source/export evidence.",
                },
            )
        )
    placeholder_metadata = (
        placeholder_source_metadata_fields(source_metadata) if review_stage == "source" else []
    )
    if placeholder_metadata and review_stage == "source":
        findings.append(
            DataSourceQAReviewFinding(
                "BLOCK",
                "SOURCE_METADATA_PLACEHOLDER",
                "Required source metadata fields contain placeholder or weak values.",
                {
                    "placeholder_metadata": placeholder_metadata,
                    "target": str(_source_qa_worksheet_path(checklist_file)),
                    "required_evidence": "Replace placeholder source_metadata values with retained real evidence.",
                },
            )
        )

    answer_map = _answers_map(answers.get("answers", {}))
    manifest_by_id = _evidence_manifest_by_id(manifest)
    if review_stage == "source":
        findings.extend(
            _evidence_manifest_findings(
                manifest_file=manifest_file,
                manifest=manifest,
                require_manifest=require_evidence_manifest,
            )
        )
    for item in checklist.get("checklist", []) or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", "")).strip()
        if str(item.get("review_stage", "source")).strip() != review_stage:
            continue
        severity = str(item.get("severity", "INFO")).upper()
        answer = answer_map.get(item_id, {})
        answer_value, evidence = _resolved_answer(
            item_id,
            answer,
            validation,
            checklist,
            review_stage=review_stage,
        )
        if severity == "BLOCK_IF_NO":
            if answer_value != "yes":
                findings.append(
                    DataSourceQAReviewFinding(
                        "BLOCK",
                        "SOURCE_QA_BLOCK_ANSWER",
                        "A BLOCK_IF_NO source QA question is unanswered or answered no.",
                        _finding_evidence_context(
                            item,
                            checklist_file=checklist_file,
                            answer=answer_value,
                        ),
                    )
                )
            elif not evidence:
                findings.append(
                    DataSourceQAReviewFinding(
                        "BLOCK",
                        "SOURCE_QA_EVIDENCE_MISSING",
                        "A BLOCK_IF_NO source QA question has no evidence note.",
                        _finding_evidence_context(
                            item,
                            checklist_file=checklist_file,
                            answer=answer_value,
                        ),
                    )
                )
            elif _evidence_is_weak(evidence):
                findings.append(
                    DataSourceQAReviewFinding(
                        "BLOCK",
                        "SOURCE_QA_EVIDENCE_PLACEHOLDER",
                        "A BLOCK_IF_NO source QA question uses placeholder or weak evidence.",
                        _finding_evidence_context(
                            item,
                            checklist_file=checklist_file,
                            answer=answer_value,
                            evidence=evidence,
                            invalid_evidence=evidence,
                        ),
                    )
                )
            elif (
                review_stage == "source"
                and require_evidence_manifest
                and item_id not in manifest_by_id
            ):
                findings.append(
                    DataSourceQAReviewFinding(
                        "BLOCK",
                        "SOURCE_QA_EVIDENCE_ATTACHMENT_MISSING",
                        "A BLOCK_IF_NO source QA question has no evidence attachment in the manifest.",
                        _finding_attachment_context(
                            item,
                            checklist_file=checklist_file,
                            manifest_file=manifest_file,
                        ),
                    )
                )
        elif severity == "WATCH_IF_NO":
            if answer_value != "yes":
                findings.append(
                    DataSourceQAReviewFinding(
                        "WATCH",
                        "SOURCE_QA_WATCH_ANSWER",
                        "A WATCH_IF_NO source QA question is unanswered or answered no.",
                        _finding_evidence_context(
                            item,
                            checklist_file=checklist_file,
                            answer=answer_value,
                        ),
                    )
                )
            elif not evidence:
                findings.append(
                    DataSourceQAReviewFinding(
                        "WATCH",
                        "SOURCE_QA_WATCH_EVIDENCE_MISSING",
                        "A WATCH_IF_NO source QA question has no evidence note.",
                        _finding_evidence_context(
                            item,
                            checklist_file=checklist_file,
                            answer=answer_value,
                        ),
                    )
                )
            elif _evidence_is_weak(evidence):
                findings.append(
                    DataSourceQAReviewFinding(
                        "WATCH",
                        "SOURCE_QA_WATCH_EVIDENCE_PLACEHOLDER",
                        "A WATCH_IF_NO source QA question uses placeholder or weak evidence.",
                        _finding_evidence_context(
                            item,
                            checklist_file=checklist_file,
                            answer=answer_value,
                            evidence=evidence,
                            invalid_evidence=evidence,
                        ),
                    )
                )
    return _review(
        checklist_path=checklist_file,
        answers_path=answers_file,
        validation_report_path=validation_file,
        evidence_manifest_path=manifest_file,
        require_evidence_manifest=require_evidence_manifest,
        review_stage=review_stage,
        source_metadata=source_metadata,
        missing_metadata=missing_metadata,
        findings=findings,
    )


def write_data_source_qa_review(review: DataSourceQAReview, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    json_name, md_name = _review_filenames(review.review_stage)
    (root / json_name).write_text(
        json.dumps(review.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / md_name).write_text(review.to_markdown(), encoding="utf-8")
    return root


def _load_config(config_path: str | Path | None) -> dict[str, Any]:
    if config_path is None:
        return {}
    return load_config(config_path).to_dict()


def _source_metadata_template(price_adjustment: str, start: str, end: str) -> dict[str, str]:
    return {
        "data_vendor_or_broker": "",
        "terminal_or_product_name": "",
        "export_operator": "",
        "exported_at_local_time": "",
        "market": "A-share equities",
        "frequency": "daily",
        "date_range": f"{start} to {end}",
        "price_adjustment": price_adjustment,
        "encoding": "utf-8-sig or gbk",
        "license_or_usage_scope": "research and paper trading only",
        "known_limitations": "",
        "reviewed_by": "",
        "reviewed_at": "",
    }


def _qa_items(price_adjustment: str) -> list[DataSourceQAItem]:
    return [
        DataSourceQAItem(
            "source_identity",
            "source",
            "source",
            "BLOCK_IF_NO",
            "Can the vendor, terminal/product, export operator, and export time be identified?",
            "Filled source_metadata fields or a vendor export receipt.",
            "Unidentified data cannot be reproduced or audited after a surprising backtest.",
        ),
        DataSourceQAItem(
            "license_scope",
            "source",
            "source",
            "BLOCK_IF_NO",
            "Is the data license limited to lawful research/paper use in this project?",
            "License note, account permission, or vendor terms kept with the export.",
            "The system must not rely on data that cannot be legally used or retained.",
        ),
        DataSourceQAItem(
            "date_window",
            "coverage",
            "csv_validation",
            "BLOCK_IF_NO",
            "Does bars.csv cover the configured research window through the latest completed trading day?",
            "Doctor/CSV validation summary showing bars_start and bars_end.",
            "Stale or partial bars can create false strategy stability.",
        ),
        DataSourceQAItem(
            "symbol_breadth",
            "coverage",
            "csv_validation",
            "BLOCK_IF_NO",
            "Does the export contain enough A-share symbols for the configured minimum universe?",
            "CSV validation metric bars_symbol_count >= min_symbols.",
            "A small universe can turn a broad-market strategy into a cherry-picked sample.",
        ),
        DataSourceQAItem(
            "price_adjustment",
            "contract",
            "source",
            "BLOCK_IF_NO",
            f"Are OHLC prices exported with the configured adjustment method `{price_adjustment}`?",
            "Vendor export setting screenshot or metadata note.",
            "Mixed raw/qfq/hfq prices invalidate returns, drawdowns, and factor ranks.",
        ),
        DataSourceQAItem(
            "calendar",
            "execution",
            "csv_validation",
            "WATCH_IF_NO",
            "Is a trading calendar supplied or clearly inferable from bars.csv?",
            "calendar.csv or validation note that calendar was inferred.",
            "Missing open-day evidence weakens missing-bar and paper execution checks.",
        ),
        DataSourceQAItem(
            "suspensions_limits",
            "execution",
            "csv_validation",
            "WATCH_IF_NO",
            "Are suspensions and limit-up/limit-down constraints available or documented as missing?",
            "suspensions.csv plus vendor notes for unavailable limit flags.",
            "Paper fills become too optimistic if non-tradable days are invisible.",
        ),
        DataSourceQAItem(
            "st_delist_flags",
            "universe",
            "csv_validation",
            "WATCH_IF_NO",
            "Does stock_info include ST and delist fields for investable-universe audit?",
            "stock_info.csv columns is_st and delist_date.",
            "ST/delist gaps can hide risks that manual trading must avoid.",
        ),
        DataSourceQAItem(
            "point_in_time",
            "lookahead",
            "source",
            "BLOCK_IF_NO",
            "Are fundamentals and index constituents point-in-time or explicitly marked as non-PIT?",
            "Vendor documentation or a note that non-PIT data must remain research-only.",
            "Non-point-in-time data can leak future information into strategy selection.",
        ),
        DataSourceQAItem(
            "file_fingerprint",
            "reproducibility",
            "csv_validation",
            "BLOCK_IF_NO",
            "Will the imported files be fingerprinted and kept unchanged after validation?",
            "csv_validation dataset_fingerprint and file sha256 values.",
            "Every research result must be traceable to the exact data batch used.",
        ),
        DataSourceQAItem(
            "manual_signoff",
            "governance",
            "source",
            "BLOCK_IF_NO",
            "Has a human reviewed source QA before strategy research uses the cache?",
            "reviewed_by and reviewed_at filled in the metadata template or approval notes.",
            "Human approval owns source risk; LLM output cannot bless uncertain data.",
        ),
    ]


def _workflow_commands(
    *,
    data_dir: Path,
    config_path: str,
    min_symbols: int,
    as_of: str | None,
) -> list[str]:
    as_of_arg = f" --as-of {as_of}" if as_of else ""
    return [
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_export_request.py "
            f"--config {config_path} --output-dir {data_dir} --min-symbols {min_symbols}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa.py "
            f"--config {config_path} --output-dir {data_dir} --min-symbols {min_symbols}{as_of_arg}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_evidence_worksheet.py "
            f"--checklist {data_dir / 'data_source_qa.json'} --output-dir {data_dir}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
            f"--checklist {data_dir / 'data_source_qa.json'} "
            f"--evidence-dir {data_dir / 'source_qa_evidence'} --output-dir {data_dir} --strict"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_answers.py "
            f"--checklist {data_dir / 'data_source_qa.json'} "
            f"--output {data_dir / 'data_source_qa_answers.json'} "
            f"--evidence-manifest {data_dir / 'source_qa_evidence_manifest.json'} "
            "--require-evidence-manifest "
            "--vendor <vendor-or-broker> --terminal <terminal-name> --operator <operator> "
            "--exported-at <local-time> --price-adjustment qfq "
            "--price-adjustment-evidence <evidence> --license-evidence <evidence> "
            "--point-in-time-evidence <evidence-or-non-pit-note> "
            "--reviewed-by <name> --reviewed-at <date>"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_preflight.py "
            f"--checklist {data_dir / 'data_source_qa.json'} "
            f"--answers {data_dir / 'data_source_qa_answers.json'} "
            "--output-dir results\\import\\source_qa"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_data_source_qa_review.py "
            f"--checklist {data_dir / 'data_source_qa.json'} "
            f"--answers {data_dir / 'data_source_qa_answers.json'} "
            f"--evidence-manifest {data_dir / 'source_qa_evidence_manifest.json'} "
            "--require-evidence-manifest --output-dir results\\import\\source_qa"
        ),
        f".\\.venv\\Scripts\\python.exe examples\\write_data_export_templates.py --output-dir {data_dir}",
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_offline_data_intake.py "
            f"--data-dir {data_dir} --config {config_path} "
            "--output-dir results\\import\\offline_intake "
            "--raw-bars-csv <raw-vendor-bars.csv> "
            "--source-vendor <vendor-or-broker> --source-terminal <terminal-name> "
            "--source-operator <operator> --source-exported-at <local-time> "
            "--source-price-adjustment qfq --source-price-adjustment-evidence <evidence> "
            "--source-license-evidence <evidence> "
            "--source-point-in-time-evidence <evidence-or-non-pit-note> "
            "--source-reviewed-by <name> --source-reviewed-at <date> "
            f"--min-symbols {min_symbols} --min-trading-days 240"
            f" --source-qa-answers {data_dir / 'data_source_qa_answers.json'}"
            f"{as_of_arg}"
        ),
    ]


def _answers_template(checklist: DataSourceQAChecklist) -> dict[str, Any]:
    return {
        "source_metadata": checklist.source_metadata_template,
        "answers": {
            item.id: {
                "answer": "",
                "evidence": "",
                "review_stage": item.review_stage,
                "severity": item.severity,
                "question": item.question,
                "required_evidence": item.required_evidence,
                "notes": "",
            }
            for item in checklist.checklist
        },
    }


def _evidence_worksheet_from_checklist(
    checklist: dict[str, Any],
    *,
    checklist_path: Path,
    output_dir: Path,
) -> SourceQAEvidenceWorksheet:
    rows = _metadata_worksheet_rows(checklist)
    rows.extend(_source_question_worksheet_rows(checklist))
    return SourceQAEvidenceWorksheet(
        checklist_path=str(checklist_path),
        rows=rows,
        workflow_commands=_worksheet_workflow_commands(
            checklist_file=checklist_path,
            output_dir=output_dir,
        ),
        safety_boundaries=[
            "This worksheet is a human evidence collection aid, not an automatic approval.",
            "Do not invent answers or evidence to make source QA pass.",
            "Leaving rows blank keeps the deterministic source QA and preflight gates BLOCK.",
            "The worksheet cannot modify PASS/WATCH/BLOCK decisions.",
            "This workflow is for research and paper trading only; it must not connect to a real broker.",
        ],
    )


def _metadata_worksheet_rows(checklist: dict[str, Any]) -> list[SourceQAEvidenceWorksheetRow]:
    template = checklist.get("source_metadata_template", {})
    template = template if isinstance(template, dict) else {}
    rows: list[SourceQAEvidenceWorksheetRow] = []
    for field in REQUIRED_SOURCE_METADATA:
        rows.append(
            SourceQAEvidenceWorksheetRow(
                row_type="metadata",
                field_or_question_id=field,
                cli_argument=_metadata_cli_argument(field),
                severity="REQUIRED",
                question_or_field=field,
                required_evidence=_metadata_required_evidence(field),
                why_it_matters=_metadata_why_it_matters(field),
                answer=str(template.get(field, "")),
            )
        )
    return rows


def _source_question_worksheet_rows(checklist: dict[str, Any]) -> list[SourceQAEvidenceWorksheetRow]:
    rows: list[SourceQAEvidenceWorksheetRow] = []
    for item in checklist.get("checklist", []) or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("review_stage", "source")) != "source":
            continue
        rows.append(
            SourceQAEvidenceWorksheetRow(
                row_type="source_question",
                field_or_question_id=str(item.get("id", "")),
                cli_argument=_source_question_cli_argument(str(item.get("id", ""))),
                severity=str(item.get("severity", "")),
                question_or_field=str(item.get("question", "")),
                required_evidence=str(item.get("required_evidence", "")),
                why_it_matters=str(item.get("why_it_matters", "")),
            )
        )
    return rows


def _metadata_cli_argument(field: str) -> str:
    return {
        "data_vendor_or_broker": "--vendor",
        "terminal_or_product_name": "--terminal",
        "export_operator": "--operator",
        "exported_at_local_time": "--exported-at",
        "price_adjustment": "--price-adjustment",
        "license_or_usage_scope": "--license-scope",
        "reviewed_by": "--reviewed-by",
        "reviewed_at": "--reviewed-at",
    }.get(field, "")


def _source_question_cli_argument(item_id: str) -> str:
    return {
        "source_identity": "--vendor/--terminal/--operator/--exported-at",
        "license_scope": "--license-evidence",
        "price_adjustment": "--price-adjustment-evidence",
        "point_in_time": "--point-in-time-evidence",
        "manual_signoff": "--reviewed-by/--reviewed-at",
    }.get(item_id, "")


def _metadata_required_evidence(field: str) -> str:
    return {
        "data_vendor_or_broker": "Exact vendor, broker, or terminal data source name.",
        "terminal_or_product_name": "Terminal/product name and version when available.",
        "export_operator": "Human or process that produced the export.",
        "exported_at_local_time": "Local timestamp for the export batch.",
        "price_adjustment": "Configured adjustment setting such as raw, qfq, or hfq.",
        "license_or_usage_scope": "Allowed use scope from vendor terms, broker account, or internal policy.",
        "reviewed_by": "Human reviewer name or identifier.",
        "reviewed_at": "Review date or timestamp.",
    }.get(field, "Concrete source metadata evidence.")


def _metadata_why_it_matters(field: str) -> str:
    return {
        "data_vendor_or_broker": "Unidentified data cannot be reproduced or challenged after a surprising result.",
        "terminal_or_product_name": "Different products can apply different adjustments, universes, or field definitions.",
        "export_operator": "A human owner is needed when the export must be reproduced or corrected.",
        "exported_at_local_time": "The export time anchors freshness and prevents stale-data promotion.",
        "price_adjustment": "Mixed price adjustment invalidates returns, drawdowns, and ranks.",
        "license_or_usage_scope": "The project must only use data it is allowed to retain and analyze.",
        "reviewed_by": "Human signoff owns source risk; LLM output cannot bless uncertain data.",
        "reviewed_at": "The review timestamp makes the evidence auditable.",
    }.get(field, "This metadata is required for source QA.")


def _worksheet_workflow_commands(*, checklist_file: Path, output_dir: Path) -> list[str]:
    answers_path = output_dir / "data_source_qa_answers.json"
    worksheet_path = output_dir / "data_source_qa_evidence_worksheet.csv"
    manifest_path = output_dir / "source_qa_evidence_manifest.json"
    evidence_dir = output_dir / "source_qa_evidence"
    return [
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_evidence_worksheet.py "
            f"--checklist {checklist_file} --output-dir {output_dir}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\fill_data_source_qa_evidence_worksheet.py "
            f"--checklist {checklist_file} --worksheet {worksheet_path} "
            "--vendor \"<vendor-or-broker>\" --terminal \"<terminal-name>\" "
            "--operator \"<operator>\" --exported-at \"<local-time>\" "
            "--price-adjustment \"<raw-or-qfq-or-hfq>\" "
            "--license-scope \"research and paper trading only\" "
            "--reviewed-by \"<name>\" --reviewed-at \"<YYYY-MM-DD>\" "
            "--source-identity-evidence \"<retained-source-identity-evidence>\" "
            "--license-evidence \"<retained-license-evidence>\" "
            "--price-adjustment-evidence \"<retained-price-adjustment-evidence>\" "
            "--point-in-time-evidence \"<retained-PIT-evidence-or-research-only-note>\" "
            "--manual-signoff-evidence \"<retained-human-review-evidence>\""
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_data_source_qa_worksheet_preflight.py "
            f"--checklist {checklist_file} --worksheet {worksheet_path} --output-dir {output_dir}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
            f"--checklist {checklist_file} --evidence-dir {evidence_dir} "
            f"--output-dir {output_dir} --strict"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_answers.py "
            f"--checklist {checklist_file} --worksheet {worksheet_path} --output {answers_path} "
            f"--evidence-manifest {manifest_path} --require-evidence-manifest"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_preflight.py "
            f"--checklist {checklist_file} --answers {answers_path} "
            f"--evidence-manifest {manifest_path} --require-evidence-manifest "
            "--output-dir results\\import\\source_qa"
        ),
    ]


def _worksheet_fieldnames() -> list[str]:
    return [
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


def _set_answer(answers: dict[str, dict[str, str]], item_id: str, evidence: str) -> None:
    if item_id not in answers:
        return
    answers[item_id]["answer"] = "yes"
    answers[item_id]["evidence"] = evidence


def _set_or_create_answer(
    answers: dict[str, dict[str, str]],
    item_id: str,
    answer: str,
    evidence: str,
    *,
    notes: str = "",
) -> None:
    if item_id not in answers:
        answers[item_id] = {"answer": "", "evidence": "", "review_stage": "source", "notes": ""}
    answers[item_id]["answer"] = answer
    answers[item_id]["evidence"] = evidence
    if notes:
        answers[item_id]["notes"] = notes


def _fill_derived_source_answers_from_metadata(
    source_metadata: dict[str, Any],
    answers: dict[str, dict[str, str]],
) -> None:
    if "source_identity" in answers and not answers["source_identity"].get("evidence"):
        fields = [
            "data_vendor_or_broker",
            "terminal_or_product_name",
            "export_operator",
            "exported_at_local_time",
        ]
        if all(str(source_metadata.get(field, "")).strip() for field in fields):
            _set_answer(
                answers,
                "source_identity",
                (
                    f"vendor={source_metadata.get('data_vendor_or_broker')}; "
                    f"terminal={source_metadata.get('terminal_or_product_name')}; "
                    f"operator={source_metadata.get('export_operator')}; "
                    f"exported_at={source_metadata.get('exported_at_local_time')}"
                ),
            )
    if "manual_signoff" in answers and not answers["manual_signoff"].get("evidence"):
        reviewed_by = str(source_metadata.get("reviewed_by", "")).strip()
        reviewed_at = str(source_metadata.get("reviewed_at", "")).strip()
        if reviewed_by and reviewed_at:
            _set_answer(answers, "manual_signoff", f"reviewed_by={reviewed_by}; reviewed_at={reviewed_at}")


def _worksheet_answer(answer: str, evidence: str) -> str:
    value = _answer_value(answer)
    if value != "unknown":
        return value
    return "yes" if evidence else ""


def _read_worksheet_rows(
    path: Path,
    *,
    encoding: str,
    worksheet_text: str | None = None,
) -> list[dict[str, str]]:
    if path.suffix.lower() == ".json":
        payload = json.loads(worksheet_text) if worksheet_text is not None else _read_json(path)
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        return [row for row in rows if isinstance(row, dict)]
    if worksheet_text is not None:
        import io

        handle = io.StringIO(worksheet_text)
        return [dict(row) for row in csv.DictReader(handle)]
    with path.open("r", newline="", encoding=encoding) as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _worksheet_metadata_preflight_findings(
    *,
    row_number: int,
    item_id: str,
    severity: str,
    answer: str,
    evidence: str,
    row: dict[str, str],
) -> list[SourceQAEvidenceWorksheetPreflightFinding]:
    if item_id not in REQUIRED_SOURCE_METADATA:
        return []
    findings: list[SourceQAEvidenceWorksheetPreflightFinding] = []
    base = {
        "row": _worksheet_preflight_row_payload(row),
        "target_field": item_id,
    }
    if not answer:
        findings.append(
            _worksheet_preflight_finding(
                "BLOCK",
                "SOURCE_QA_WORKSHEET_METADATA_MISSING",
                row_number=row_number,
                row_type="metadata",
                field_or_question_id=item_id,
                severity=severity,
                message="Required source metadata answer is missing.",
                fix=f"Fill `{item_id}` from the real export batch or retained vendor evidence.",
                evidence=base,
            )
        )
    elif weak_source_evidence(answer):
        findings.append(
            _worksheet_preflight_finding(
                "BLOCK",
                "SOURCE_QA_WORKSHEET_METADATA_PLACEHOLDER",
                row_number=row_number,
                row_type="metadata",
                field_or_question_id=item_id,
                severity=severity,
                message="Required source metadata answer looks like a placeholder.",
                fix=f"Replace `{item_id}` with real source metadata from the export batch.",
                evidence={**base, "answer": answer},
            )
        )
    if not evidence:
        findings.append(
            _worksheet_preflight_finding(
                "BLOCK",
                "SOURCE_QA_WORKSHEET_METADATA_EVIDENCE_MISSING",
                row_number=row_number,
                row_type="metadata",
                field_or_question_id=item_id,
                severity=severity,
                message="Required source metadata row has no evidence note.",
                fix="Add a concrete evidence note tied to the vendor export, license, or review record.",
                evidence=base,
            )
        )
    elif weak_source_evidence(evidence):
        findings.append(
            _worksheet_preflight_finding(
                "BLOCK",
                "SOURCE_QA_WORKSHEET_METADATA_EVIDENCE_PLACEHOLDER",
                row_number=row_number,
                row_type="metadata",
                field_or_question_id=item_id,
                severity=severity,
                message="Required source metadata evidence looks weak or placeholder-like.",
                fix="Replace the evidence note with a concrete retained source/export reference.",
                evidence={**base, "evidence": evidence},
            )
        )
    findings.extend(
        _worksheet_generated_reference_findings(
            row_number=row_number,
            row_type="metadata",
            item_id=item_id,
            severity=severity,
            evidence_text=evidence,
            row=row,
        )
    )
    return findings


def _worksheet_source_question_preflight_findings(
    *,
    row_number: int,
    item_id: str,
    severity: str,
    answer: str,
    evidence: str,
    row: dict[str, str],
) -> list[SourceQAEvidenceWorksheetPreflightFinding]:
    if severity not in {"BLOCK_IF_NO", "WATCH_IF_NO"}:
        if not evidence:
            return []
        return _worksheet_generated_reference_findings(
            row_number=row_number,
            row_type="source_question",
            item_id=item_id,
            severity=severity,
            evidence_text=evidence,
            row=row,
        )
    status: QAStatus = "BLOCK" if severity == "BLOCK_IF_NO" else "WATCH"
    findings: list[SourceQAEvidenceWorksheetPreflightFinding] = []
    base = {
        "row": _worksheet_preflight_row_payload(row),
        "target_question": item_id,
    }
    answer_value = _answer_value(answer)
    if answer_value != "yes":
        code = "SOURCE_QA_WORKSHEET_BLOCK_ANSWER"
        if status == "WATCH":
            code = "SOURCE_QA_WORKSHEET_WATCH_ANSWER"
        findings.append(
            _worksheet_preflight_finding(
                status,
                code,
                row_number=row_number,
                row_type="source_question",
                field_or_question_id=item_id,
                severity=severity,
                message=f"{severity} source QA question is not explicitly answered yes.",
                fix="Answer yes only after the required evidence exists; otherwise keep the gate open.",
                evidence={**base, "answer": answer},
            )
        )
    if not evidence:
        code = "SOURCE_QA_WORKSHEET_EVIDENCE_MISSING"
        if status == "WATCH":
            code = "SOURCE_QA_WORKSHEET_WATCH_EVIDENCE_MISSING"
        findings.append(
            _worksheet_preflight_finding(
                status,
                code,
                row_number=row_number,
                row_type="source_question",
                field_or_question_id=item_id,
                severity=severity,
                message=f"{severity} source QA question has no evidence note.",
                fix="Add concrete retained source evidence before generating answers.",
                evidence=base,
            )
        )
    elif weak_source_evidence(evidence):
        code = "SOURCE_QA_WORKSHEET_EVIDENCE_PLACEHOLDER"
        if status == "WATCH":
            code = "SOURCE_QA_WORKSHEET_WATCH_EVIDENCE_PLACEHOLDER"
        findings.append(
            _worksheet_preflight_finding(
                status,
                code,
                row_number=row_number,
                row_type="source_question",
                field_or_question_id=item_id,
                severity=severity,
                message=f"{severity} source QA evidence looks weak or placeholder-like.",
                fix="Replace sample or placeholder evidence with a concrete retained source reference.",
                evidence={**base, "evidence": evidence},
            )
        )
    findings.extend(
        _worksheet_generated_reference_findings(
            row_number=row_number,
            row_type="source_question",
            item_id=item_id,
            severity=severity,
            evidence_text=evidence,
            row=row,
        )
    )
    return findings


def _worksheet_generated_reference_findings(
    *,
    row_number: int,
    row_type: str,
    item_id: str,
    severity: str,
    evidence_text: str,
    row: dict[str, str],
) -> list[SourceQAEvidenceWorksheetPreflightFinding]:
    reason = _worksheet_generated_evidence_reference_reason(evidence_text)
    if not reason:
        return []
    return [
        _worksheet_preflight_finding(
            "BLOCK",
            "SOURCE_QA_WORKSHEET_GENERATED_EVIDENCE_REFERENCE",
            row_number=row_number,
            row_type=row_type,
            field_or_question_id=item_id,
            severity=severity,
            message="Worksheet evidence appears to reference a generated workflow aid.",
            fix="Use retained vendor/export evidence, not worksheet/template/sample/plan artifacts.",
            evidence={
                "row": _worksheet_preflight_row_payload(row),
                "evidence": evidence_text,
                "generated_reference_reason": reason,
            },
        )
    ]


def _worksheet_generated_evidence_reference_reason(text: str) -> str:
    for candidate in _worksheet_evidence_reference_candidates(text):
        reason = _generated_attachment_path_reason(Path(candidate))
        if reason:
            return f"{reason}:{candidate}"
    return ""


def _worksheet_evidence_reference_candidates(text: str) -> list[str]:
    if not text:
        return []
    pattern = re.compile(
        r"(?:[A-Za-z]:)?[A-Za-z0-9_. -]*[\\/][A-Za-z0-9_.\\/ -]+"
        r"|[A-Za-z0-9_.-]+\.(?:csv|json|yaml|yml|md|txt|log|pdf|png|jpg|jpeg|xlsx)",
        re.IGNORECASE,
    )
    candidates: list[str] = []
    for match in pattern.finditer(text):
        candidate = match.group(0).strip().strip("`'\"()[]{}.,;")
        if candidate:
            candidates.append(candidate)
    return candidates


def _worksheet_preflight_finding(
    status: QAStatus,
    code: str,
    *,
    row_number: int,
    row_type: str,
    field_or_question_id: str,
    severity: str,
    message: str,
    fix: str,
    evidence: dict[str, Any],
) -> SourceQAEvidenceWorksheetPreflightFinding:
    return SourceQAEvidenceWorksheetPreflightFinding(
        status=status,
        code=code,
        row_number=row_number,
        row_type=row_type,
        field_or_question_id=field_or_question_id,
        severity=severity,
        message=message,
        fix=fix,
        evidence=evidence,
    )


def _worksheet_preflight_row_payload(row: dict[str, str]) -> dict[str, str]:
    return {
        "row_type": str(row.get("row_type", "")).strip(),
        "field_or_question_id": str(row.get("field_or_question_id", "")).strip(),
        "severity": str(row.get("severity", "")).strip(),
        "question_or_field": str(row.get("question_or_field", "")).strip(),
        "required_evidence": str(row.get("required_evidence", "")).strip(),
    }


def _worksheet_preflight_next_commands(
    *,
    checklist_file: Path,
    worksheet_file: Path,
    status: QAStatus,
) -> list[str]:
    answers_path = worksheet_file.parent / "data_source_qa_answers.json"
    manifest_path = worksheet_file.parent / "source_qa_evidence_manifest.json"
    evidence_dir = worksheet_file.parent / "source_qa_evidence"
    if status == "BLOCK":
        return [
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_data_source_qa_worksheet_preflight.py "
                f"--checklist {checklist_file} --worksheet {worksheet_file} "
                f"--output-dir {worksheet_file.parent}"
            )
        ]
    return [
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
            f"--checklist {checklist_file} --evidence-dir {evidence_dir} "
            f"--output-dir {worksheet_file.parent} --strict"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_answers.py "
            f"--checklist {checklist_file} --worksheet {worksheet_file} --output {answers_path} "
            f"--evidence-manifest {manifest_path} --require-evidence-manifest"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_preflight.py "
            f"--checklist {checklist_file} --answers {answers_path} "
            f"--evidence-manifest {manifest_path} --require-evidence-manifest "
            "--output-dir results\\import\\source_qa"
        ),
    ]


def _required_source_question_ids(checklist: dict[str, Any], seen: set[str]) -> list[str]:
    missing: list[str] = []
    for item in checklist.get("checklist", []) if isinstance(checklist, dict) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("review_stage", "source")) != "source":
            continue
        if str(item.get("severity", "")).upper() not in {"BLOCK_IF_NO", "WATCH_IF_NO"}:
            continue
        item_id = str(item.get("id", "")).strip()
        if item_id and item_id not in seen:
            missing.append(item_id)
    return missing


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _metadata(answers: dict[str, Any]) -> dict[str, Any]:
    metadata = answers.get("source_metadata", {})
    return metadata if isinstance(metadata, dict) else {}


def _answers_map(raw_answers: object) -> dict[str, dict[str, Any]]:
    if isinstance(raw_answers, dict):
        return {
            str(key): value if isinstance(value, dict) else {"answer": value}
            for key, value in raw_answers.items()
        }
    if isinstance(raw_answers, list):
        mapped = {}
        for item in raw_answers:
            if isinstance(item, dict) and "id" in item:
                mapped[str(item["id"])] = item
        return mapped
    return {}


def _resolved_answer(
    item_id: str,
    answer: dict[str, Any],
    validation: dict[str, Any],
    checklist: dict[str, Any],
    *,
    review_stage: QAReviewStage,
) -> tuple[str, str]:
    if review_stage == "csv_validation":
        auto_answer = _csv_validation_answer(item_id, validation, checklist)
        if auto_answer is not None:
            return auto_answer
    return _answer_value(answer.get("answer")), str(answer.get("evidence", "")).strip()


def _csv_validation_answer(
    item_id: str,
    validation: dict[str, Any],
    checklist: dict[str, Any],
) -> tuple[str, str] | None:
    if not validation:
        return "unknown", "csv_validation.json is missing."
    metrics = validation.get("metrics", {}) or {}
    files = validation.get("files", []) or []
    expected_start = str(checklist.get("start", "") or "")
    expected_end = str(checklist.get("end", "") or "")
    min_symbols = int(checklist.get("min_symbols", 0) or 0)
    if item_id == "date_window":
        bars_start = str(metrics.get("bars_start", "") or "")
        bars_end = str(metrics.get("bars_end", "") or "")
        ok = bool(bars_start and bars_end)
        if expected_start:
            ok = ok and bars_start <= expected_start
        if expected_end:
            ok = ok and bars_end >= expected_end
        return (
            "yes" if ok else "no",
            f"bars_start={bars_start or 'missing'}, bars_end={bars_end or 'missing'}",
        )
    if item_id == "symbol_breadth":
        symbol_count = int(metrics.get("bars_symbol_count", 0) or 0)
        return (
            "yes" if symbol_count >= min_symbols else "no",
            f"bars_symbol_count={symbol_count}, min_symbols={min_symbols}",
        )
    if item_id == "file_fingerprint":
        fingerprint = str(validation.get("dataset_fingerprint", "") or "")
        sha_count = sum(1 for item in files if isinstance(item, dict) and item.get("sha256"))
        return (
            "yes" if fingerprint and sha_count else "no",
            f"dataset_fingerprint={fingerprint[:12] or 'missing'}, file_sha_count={sha_count}",
        )
    if item_id == "calendar":
        exists = _file_exists(files, "calendar")
        return ("yes" if exists else "no", "calendar.csv present" if exists else "calendar.csv missing")
    if item_id == "suspensions_limits":
        exists = _file_exists(files, "suspensions")
        evidence = "suspensions.csv present; limit flags may still require vendor notes"
        return ("yes" if exists else "no", evidence if exists else "suspensions.csv missing")
    if item_id == "st_delist_flags":
        stock_info = _file_summary(files, "stock_info")
        columns = set(stock_info.get("columns", []) if stock_info else [])
        ok = bool(stock_info and stock_info.get("exists") and {"is_st", "delist_date"}.issubset(columns))
        return (
            "yes" if ok else "no",
            f"stock_info_columns={','.join(sorted(columns)) if columns else 'missing'}",
        )
    return None


def _file_summary(files: list[Any], role: str) -> dict[str, Any]:
    for item in files:
        if isinstance(item, dict) and item.get("role") == role:
            return item
    return {}


def _file_exists(files: list[Any], role: str) -> bool:
    return bool(_file_summary(files, role).get("exists"))


def placeholder_source_metadata_fields(metadata: dict[str, Any]) -> list[str]:
    return [
        key
        for key in REQUIRED_SOURCE_METADATA
        if _looks_like_placeholder(str(metadata.get(key, "")))
    ]


def weak_source_evidence(text: object) -> bool:
    return _evidence_is_weak(str(text or ""))


def _evidence_id_from_path(path: Path, source_ids: list[str]) -> str:
    lower_name = path.name.lower()
    lower_stem = path.stem.lower()
    for item_id in sorted(source_ids, key=len, reverse=True):
        lowered = item_id.lower()
        if lower_stem == lowered or lower_stem.startswith(f"{lowered}_") or lower_stem.startswith(
            f"{lowered}-"
        ):
            return item_id
        if f"_{lowered}_" in lower_name or f"-{lowered}-" in lower_name:
            return item_id
    return ""


def _evidence_manifest_by_id(manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_id: dict[str, list[dict[str, Any]]] = {}
    for item in manifest.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", "")).strip()
        if not item_id:
            continue
        by_id.setdefault(item_id, []).append(item)
    return by_id


def _finding_evidence_context(
    item: dict[str, Any],
    *,
    checklist_file: Path,
    answer: str = "",
    evidence: str = "",
    invalid_evidence: str = "",
) -> dict[str, Any]:
    item_id = str(item.get("id", "")).strip()
    payload: dict[str, Any] = {
        "id": item_id,
        "question": str(item.get("question", "")),
        "required_evidence": str(item.get("required_evidence", "")),
        "target": str(_source_qa_worksheet_path(checklist_file)),
    }
    if answer:
        payload["answer"] = answer
    if evidence:
        payload["evidence"] = evidence
    if invalid_evidence:
        payload["invalid_evidence"] = invalid_evidence
    return payload


def _finding_attachment_context(
    item: dict[str, Any],
    *,
    checklist_file: Path,
    manifest_file: Path | None,
) -> dict[str, Any]:
    item_id = str(item.get("id", "")).strip()
    return {
        "id": item_id,
        "attachment_id": item_id,
        "question": str(item.get("question", "")),
        "required_evidence": str(item.get("required_evidence", "")),
        "target": str(_source_qa_attachment_target(checklist_file, item_id)),
        "evidence_manifest_path": str(manifest_file or ""),
    }


def _manifest_attachment_context(
    *,
    item_id: str,
    path_text: str,
    manifest_file: Path | None = None,
    invalid_attachment_reason: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": item_id,
        "attachment_id": item_id,
        "path": path_text,
        "target": path_text,
        "invalid_attachment_reason": invalid_attachment_reason,
    }
    if manifest_file is not None:
        payload["evidence_manifest_path"] = str(manifest_file)
    if extra:
        payload.update(extra)
    return payload


def _source_qa_worksheet_path(checklist_file: Path) -> Path:
    return checklist_file.parent / "data_source_qa_evidence_worksheet.csv"


def _source_qa_attachment_target(checklist_file: Path, item_id: str) -> Path:
    return checklist_file.parent / "source_qa_evidence" / _source_qa_attachment_file_name(item_id)


def _source_qa_attachment_file_name(item_id: str) -> str:
    names = {
        "source_identity": "source_identity_receipt.png",
        "license_scope": "license_scope_note.pdf",
        "price_adjustment": "price_adjustment_qfq.png",
        "point_in_time": "point_in_time_note.md",
        "manual_signoff": "manual_signoff.md",
    }
    return names.get(item_id, f"{item_id or 'source_qa'}_evidence.txt")


def _evidence_manifest_findings(
    *,
    manifest_file: Path | None,
    manifest: dict[str, Any],
    require_manifest: bool,
) -> list[DataSourceQAReviewFinding]:
    findings: list[DataSourceQAReviewFinding] = []
    if manifest_file is None:
        if require_manifest:
            findings.append(
                DataSourceQAReviewFinding(
                    "BLOCK",
                    "SOURCE_QA_EVIDENCE_MANIFEST_MISSING",
                    "Strict source QA requires source_qa_evidence_manifest.json.",
                    {
                        "evidence_manifest_path": "",
                        "target": "source_qa_evidence_manifest.json",
                    },
                )
            )
        return findings
    if not manifest_file.exists():
        findings.append(
            DataSourceQAReviewFinding(
                "BLOCK" if require_manifest else "WATCH",
                "SOURCE_QA_EVIDENCE_MANIFEST_MISSING",
                "source_qa_evidence_manifest.json is missing.",
                {
                    "evidence_manifest_path": str(manifest_file),
                    "target": str(manifest_file),
                },
            )
        )
        return findings
    items = manifest.get("items", []) if isinstance(manifest, dict) else []
    if require_manifest and not items:
        findings.append(
            DataSourceQAReviewFinding(
                "BLOCK",
                "SOURCE_QA_EVIDENCE_MANIFEST_EMPTY",
                "Strict source QA requires at least one evidence attachment.",
                {
                    "evidence_manifest_path": str(manifest_file),
                    "target": str(manifest_file),
                },
            )
        )
    for item in items or []:
        if not isinstance(item, dict):
            findings.append(
                DataSourceQAReviewFinding(
                    "BLOCK",
                    "SOURCE_QA_EVIDENCE_MANIFEST_INVALID",
                    "Evidence manifest contains a non-object item.",
                    {
                        "evidence_manifest_path": str(manifest_file),
                        "target": str(manifest_file),
                        "invalid_attachment_reason": "manifest_item_invalid",
                    },
                )
            )
            continue
        item_id = str(item.get("id", "")).strip()
        path_text = str(item.get("path", "")).strip()
        expected_sha = str(item.get("sha256", "")).strip()
        attachment_error = validate_source_qa_attachment(
            item_id=item_id,
            path_text=path_text,
            sha256=expected_sha,
        )
        if attachment_error is None:
            continue
        error_code = str(attachment_error.get("code", "attachment_invalid"))
        if error_code in {"id_missing", "path_missing"}:
            findings.append(
                DataSourceQAReviewFinding(
                    "BLOCK",
                    "SOURCE_QA_EVIDENCE_MANIFEST_INVALID",
                    str(attachment_error.get("message", "Evidence manifest item is invalid.")),
                    _manifest_attachment_context(
                        item_id=item_id,
                        path_text=path_text,
                        manifest_file=manifest_file,
                        invalid_attachment_reason=error_code,
                    ),
                )
            )
            continue
        if error_code == "sha256_invalid":
            findings.append(
                DataSourceQAReviewFinding(
                    "BLOCK",
                    "SOURCE_QA_EVIDENCE_ATTACHMENT_HASH_INVALID",
                    str(attachment_error.get("message", "Evidence attachment sha256 is invalid.")),
                    _manifest_attachment_context(
                        item_id=item_id,
                        path_text=path_text,
                        manifest_file=manifest_file,
                        invalid_attachment_reason=error_code,
                        extra={
                            "sha256": expected_sha,
                            "expected_sha256_format": "64 lowercase or uppercase hexadecimal characters",
                        },
                    ),
                )
            )
            continue
        if error_code == "file_missing":
            findings.append(
                DataSourceQAReviewFinding(
                    "BLOCK",
                    "SOURCE_QA_EVIDENCE_ATTACHMENT_MISSING_FILE",
                    str(attachment_error.get("message", "Evidence attachment file is missing.")),
                    _manifest_attachment_context(
                        item_id=item_id,
                        path_text=path_text,
                        manifest_file=manifest_file,
                        invalid_attachment_reason=error_code,
                    ),
                )
            )
            continue
        if error_code == "sha256_mismatch":
            findings.append(
                DataSourceQAReviewFinding(
                    "BLOCK",
                    "SOURCE_QA_EVIDENCE_ATTACHMENT_HASH_MISMATCH",
                    str(attachment_error.get("message", "Evidence attachment sha256 does not match.")),
                    _manifest_attachment_context(
                        item_id=item_id,
                        path_text=path_text,
                        manifest_file=manifest_file,
                        invalid_attachment_reason=error_code,
                        extra={
                            "expected": expected_sha,
                            "actual": str(attachment_error.get("actual", "")),
                        },
                    ),
                )
            )
            continue
        if error_code in {"placeholder_content", "generated_artifact_path"}:
            invalid_reason = "generated_artifact_path" if error_code == "generated_artifact_path" else "placeholder_content"
            reason = str(
                attachment_error.get("placeholder_reason")
                or attachment_error.get("path_reason")
                or ""
            )
            extra = {
                "placeholder_reason": reason,
                "path_reason": reason if error_code == "generated_artifact_path" else "",
            }
            findings.append(
                DataSourceQAReviewFinding(
                    "BLOCK",
                    "SOURCE_QA_EVIDENCE_ATTACHMENT_PLACEHOLDER",
                    str(
                        attachment_error.get(
                            "message",
                            "Evidence attachment content looks like a placeholder or generated sample.",
                        )
                    ),
                    _manifest_attachment_context(
                        item_id=item_id,
                        path_text=path_text,
                        manifest_file=manifest_file,
                        invalid_attachment_reason=invalid_reason,
                        extra=extra,
                    ),
                )
            )
            continue
    return findings


def _manifest_preflight_finding(
    status: QAStatus,
    code: str,
    item_id: str,
    message: str,
    fix: str,
    evidence: dict[str, Any],
) -> SourceQAEvidenceManifestPreflightFinding:
    return SourceQAEvidenceManifestPreflightFinding(
        status=status,
        code=code,
        item_id=item_id,
        message=message,
        fix=fix,
        evidence=evidence,
    )


def _manifest_preflight_error_code(error_code: str) -> str:
    return {
        "id_missing": "SOURCE_QA_EVIDENCE_ATTACHMENT_ID_MISSING",
        "path_missing": "SOURCE_QA_EVIDENCE_ATTACHMENT_PATH_MISSING",
        "sha256_invalid": "SOURCE_QA_EVIDENCE_ATTACHMENT_HASH_INVALID",
        "file_missing": "SOURCE_QA_EVIDENCE_ATTACHMENT_MISSING_FILE",
        "sha256_mismatch": "SOURCE_QA_EVIDENCE_ATTACHMENT_HASH_MISMATCH",
        "placeholder_content": "SOURCE_QA_EVIDENCE_ATTACHMENT_PLACEHOLDER",
        "generated_artifact_path": "SOURCE_QA_EVIDENCE_ATTACHMENT_GENERATED_PATH",
    }.get(error_code, "SOURCE_QA_EVIDENCE_ATTACHMENT_INVALID")


def _manifest_preflight_fix(error_code: str) -> str:
    if error_code in {"id_missing", "path_missing", "sha256_invalid"}:
        return "Regenerate source_qa_evidence_manifest.json from retained local evidence files."
    if error_code in {"file_missing", "sha256_mismatch"}:
        return "Restore or replace the retained evidence file, then regenerate the manifest."
    if error_code in {"placeholder_content", "generated_artifact_path"}:
        return "Replace generated or placeholder material with retained vendor/export evidence."
    return "Fix the manifest item, then rerun manifest preflight."


def _manifest_preflight_next_commands(
    *,
    checklist_file: Path,
    manifest_file: Path,
    evidence_dir: Path,
    status: QAStatus,
) -> list[str]:
    if status == "PASS":
        return [
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_preflight.py "
                f"--checklist {checklist_file} "
                f"--answers {manifest_file.parent / 'data_source_qa_answers.json'} "
                f"--evidence-manifest {manifest_file} --require-evidence-manifest "
                "--output-dir results\\import\\source_qa"
            )
        ]
    return [
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
            f"--checklist {checklist_file} --evidence-dir {evidence_dir} "
            f"--output-dir {manifest_file.parent} --strict"
        )
    ]


def validate_source_qa_attachment(
    *,
    item_id: str,
    path_text: str,
    sha256: str,
) -> dict[str, str] | None:
    item_id = str(item_id or "").strip()
    path_text = str(path_text or "").strip()
    expected_sha = str(sha256 or "").strip()
    if not item_id:
        return {
            "id": item_id,
            "path": path_text,
            "code": "id_missing",
            "message": "Manifest attachment is missing its source QA id.",
        }
    if not path_text:
        return {
            "id": item_id,
            "path": path_text,
            "code": "path_missing",
            "message": "Manifest attachment is missing its local file path.",
        }
    if not _looks_like_sha256(expected_sha):
        return {
            "id": item_id,
            "path": path_text,
            "code": "sha256_invalid",
            "sha256": expected_sha,
            "message": "Manifest attachment sha256 must be a 64-character hex digest.",
        }
    path = Path(path_text)
    if not path.exists():
        return {
            "id": item_id,
            "path": path_text,
            "code": "file_missing",
            "message": "Manifest attachment file is missing from disk.",
        }
    path_reason = _generated_attachment_path_reason(path)
    if path_reason:
        return {
            "id": item_id,
            "path": path_text,
            "code": "generated_artifact_path",
            "path_reason": path_reason,
            "message": (
                "Manifest attachment path looks like a generated workflow aid; "
                "use a retained vendor/export evidence file instead."
            ),
        }
    actual = _file_sha256(path)
    if actual != expected_sha.lower():
        return {
            "id": item_id,
            "path": path_text,
            "code": "sha256_mismatch",
            "expected": expected_sha,
            "actual": actual,
            "message": "Manifest attachment sha256 no longer matches the local file.",
        }
    placeholder_reason = _placeholder_attachment_reason(path)
    if placeholder_reason:
        return {
            "id": item_id,
            "path": path_text,
            "code": "placeholder_content",
            "placeholder_reason": placeholder_reason,
            "message": "Manifest attachment content looks like placeholder, sample, or generated evidence.",
        }
    return None


def _missing_required_metadata(metadata: dict[str, Any]) -> list[str]:
    return [key for key in REQUIRED_SOURCE_METADATA if not str(metadata.get(key, "")).strip()]


def _evidence_is_weak(text: str) -> bool:
    normalized = _normalize_placeholder_text(text)
    if not normalized:
        return True
    if _looks_like_placeholder(text):
        return True
    return normalized in {"sample evidence", "test evidence", "unit test evidence"}


def _placeholder_attachment_reason(path: Path) -> str:
    if path.suffix.lower() not in _PLACEHOLDER_ATTACHMENT_SUFFIXES:
        return ""
    try:
        raw = path.read_bytes()[:_ATTACHMENT_TEXT_SAMPLE_BYTES]
    except OSError:
        return ""
    if b"\x00" in raw:
        return ""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("gb18030")
        except UnicodeDecodeError:
            return ""
    return _placeholder_text_reason(text)


def _generated_attachment_path_reason(path: Path) -> str:
    inspected_parts = _evidence_relative_parts(path)
    name_key = _attachment_path_key(Path(inspected_parts[-1]).stem if inspected_parts else path.stem)
    if name_key in _GENERATED_ATTACHMENT_FILE_NAMES:
        return f"generated_workflow_file:{name_key}"
    for token in _attachment_path_tokens(inspected_parts):
        if token in _FORBIDDEN_ATTACHMENT_PATH_TOKENS:
            return f"generated_workflow_path_token:{token}"
    return ""


def _evidence_relative_parts(path: Path) -> list[str]:
    parts = [str(part) for part in path.parts if str(part)]
    lowered = [part.lower() for part in parts]
    if "source_qa_evidence" in lowered:
        index = lowered.index("source_qa_evidence")
        relative = parts[index + 1 :]
        return relative or [path.name]
    return [path.name]


def _attachment_path_tokens(parts: list[str]) -> list[str]:
    tokens: list[str] = []
    for part in parts:
        tokens.extend(re.findall(r"[a-z0-9]+", part.lower()))
    return tokens


def _attachment_path_key(value: str) -> str:
    return "-".join(re.findall(r"[a-z0-9]+", value.lower()))


def _placeholder_text_reason(text: str) -> str:
    normalized = _normalize_placeholder_text(text)
    if not normalized:
        return "empty_text_attachment"
    if _looks_like_placeholder(text):
        return "placeholder_value"
    if normalized in {"sample evidence", "test evidence", "unit test evidence"}:
        return "sample_evidence"
    suspicious_phrases = {
        "placeholder evidence",
        "sample evidence for",
        "generated placeholder",
        "generated receipt",
        "generated sample",
        "fake evidence",
        "mock evidence",
        "unit test evidence",
        "todo evidence",
        "retained source qa evidence for",
        "real retained evidence attachment for",
    }
    for phrase in suspicious_phrases:
        if phrase in normalized:
            return phrase.replace(" ", "_")
    return ""


def _looks_like_placeholder(text: str) -> bool:
    normalized = _normalize_placeholder_text(text)
    if not normalized:
        return False
    if _ANGLE_PLACEHOLDER_RE.search(text.strip()):
        return True
    if normalized in _PLACEHOLDER_VALUES:
        return True
    return any(normalized.startswith(prefix) for prefix in _PLACEHOLDER_PREFIXES)


def _looks_like_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_placeholder_text(text: str) -> str:
    return " ".join(text.strip().lower().replace("_", "-").split())


def _answer_value(value: object) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    text = str(value or "").strip().lower()
    if text in {"yes", "y", "true", "1", "pass", "ok", "confirmed"}:
        return "yes"
    if text in {"no", "n", "false", "0", "fail", "blocked"}:
        return "no"
    return "unknown"


def _review(
    *,
    checklist_path: Path,
    answers_path: Path,
    validation_report_path: Path | None,
    evidence_manifest_path: Path | None = None,
    require_evidence_manifest: bool = False,
    review_stage: QAReviewStage,
    source_metadata: dict[str, Any],
    missing_metadata: list[str],
    findings: list[DataSourceQAReviewFinding],
) -> DataSourceQAReview:
    return DataSourceQAReview(
        status=_review_status(findings),
        review_stage=review_stage,
        checklist_path=str(checklist_path),
        answers_path=str(answers_path),
        validation_report_path=str(validation_report_path or ""),
        evidence_manifest_path=str(evidence_manifest_path or ""),
        require_evidence_manifest=require_evidence_manifest,
        source_metadata=source_metadata,
        missing_metadata=missing_metadata,
        findings=findings,
        next_actions=_review_next_actions(findings),
        prohibited_actions=[
            "Do not import CSV files into the research cache while source QA is BLOCK.",
            "Do not treat source QA PASS as strategy approval or profit evidence.",
            "Do not let LLM output override missing source evidence or human signoff.",
            "Do not connect source QA artifacts to real broker order submission.",
        ],
    )


def _review_status(findings: list[DataSourceQAReviewFinding]) -> QAStatus:
    if any(finding.severity == "BLOCK" for finding in findings):
        return "BLOCK"
    if any(finding.severity == "WATCH" for finding in findings):
        return "WATCH"
    return "PASS"


def _review_next_actions(findings: list[DataSourceQAReviewFinding]) -> list[str]:
    codes = {finding.code for finding in findings}
    actions: list[str] = []
    if "SOURCE_QA_CHECKLIST_MISSING" in codes:
        return ["Run write_data_source_qa.py to generate data_source_qa.json before import."]
    if "SOURCE_QA_ANSWERS_MISSING" in codes or "SOURCE_METADATA_MISSING" in codes:
        actions.append(
            "Fill the source QA evidence worksheet from real vendor/export evidence, write data_source_qa_answers.json, then rerun QA review."
        )
    for finding in findings:
        if finding.code in {
            "SOURCE_QA_BLOCK_ANSWER",
            "SOURCE_QA_EVIDENCE_MISSING",
            "SOURCE_QA_EVIDENCE_PLACEHOLDER",
            "SOURCE_QA_WATCH_ANSWER",
            "SOURCE_QA_WATCH_EVIDENCE_MISSING",
            "SOURCE_QA_WATCH_EVIDENCE_PLACEHOLDER",
        }:
            actions.append(_source_qa_finding_action(finding))
        elif finding.code == "SOURCE_QA_EVIDENCE_ATTACHMENT_MISSING":
            actions.append(_source_qa_attachment_action(finding))
        elif finding.code.startswith("SOURCE_QA_EVIDENCE_ATTACHMENT_") or finding.code == "SOURCE_QA_EVIDENCE_MANIFEST_INVALID":
            actions.append(_source_qa_invalid_attachment_action(finding))
    if any(finding.severity == "BLOCK" for finding in findings):
        actions.append("Resolve every BLOCK source QA finding before writing the research cache.")
        return _dedupe_actions(actions)
    if any(finding.severity == "WATCH" for finding in findings):
        actions.append("Review WATCH source QA findings and keep them with the import evidence.")
        return _dedupe_actions(actions)
    return ["Source QA review passed; continue to CSV doctor and guarded offline intake."]


def _source_qa_finding_action(finding: DataSourceQAReviewFinding) -> str:
    evidence = finding.evidence
    item_id = str(evidence.get("id", "source_qa")).strip() or "source_qa"
    target = str(evidence.get("target", "data_source_qa_evidence_worksheet.csv"))
    required = str(evidence.get("required_evidence", "retained real source evidence"))
    return f"Fill source QA worksheet item `{item_id}` in {target}: {required}"


def _source_qa_attachment_action(finding: DataSourceQAReviewFinding) -> str:
    evidence = finding.evidence
    item_id = str(evidence.get("attachment_id") or evidence.get("id") or "source_qa").strip()
    target = str(evidence.get("target") or "data_exports/source_qa_evidence")
    required = str(evidence.get("required_evidence") or "retained real source QA attachment")
    return f"Attach retained evidence for `{item_id}` at {target}: {required}"


def _source_qa_invalid_attachment_action(finding: DataSourceQAReviewFinding) -> str:
    evidence = finding.evidence
    item_id = str(evidence.get("attachment_id") or evidence.get("id") or "unknown").strip()
    target = str(evidence.get("target") or evidence.get("path") or "source_qa_evidence_manifest.json")
    reason = str(evidence.get("invalid_attachment_reason") or finding.code)
    return f"Fix source QA attachment `{item_id}` at {target}: {reason}."


def _dedupe_actions(actions: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in actions if item))


def _review_filenames(review_stage: QAReviewStage) -> tuple[str, str]:
    if review_stage == "csv_validation":
        return "data_source_csv_qa_review.json", "data_source_csv_qa_review.md"
    return "data_source_qa_review.json", "data_source_qa_review.md"
